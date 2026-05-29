import logging
import os
from datetime import datetime, timedelta, date
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
import uvicorn
from fastapi import FastAPI, Request

# Importa as funções do banco de dados
import db

load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN")
PORT = int(os.environ.get("PORT", 8080))
WEBHOOK_URL = os.environ.get("RENDER_EXTERNAL_URL", "")  # Só existe no Render

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==================== HANDLERS DO BOT ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [KeyboardButton("/add")],
        [KeyboardButton("/list"), KeyboardButton("/saldo")],
        [KeyboardButton("/setsaldo"), KeyboardButton("/delete")],
        [KeyboardButton("/semana"), KeyboardButton("/mes")],
        [KeyboardButton("/start")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(
        "💰 *Bot de Gastos Pessoais*\n\n"
        "Use os botões abaixo ou os comandos:\n"
        "/add valor categoria [descrição]\n"
        "/list - escolhe o mês\n"
        "/saldo - mostra saldo atual\n"
        "/setsaldo valor - define saldo inicial\n"
        "/semana - resumo dos últimos 7 dias\n"
        "/mes - resumo do mês atual\n"
        "/delete id - remove uma despesa",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )

async def add_expense(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Adiciona uma despesa e atualiza o saldo."""
    try:
        args = context.args
        if not args:
            await update.message.reply_text(
                "Uso: `/add valor categoria [descrição]`\nEx: `/add 35.50 mercado`",
                parse_mode="Markdown"
            )
            return
        
        amount = float(args[0].replace(",", "."))
        category = args[1]
        description = " ".join(args[2:]) if len(args) > 2 else ""
        telegram_id = update.effective_user.id
        
        # Adiciona a despesa
        expense = db.add_expense(telegram_id, amount, category, description)
        if not expense:
            await update.message.reply_text("❌ Erro ao salvar despesa.")
            return
        
        # Atualiza o saldo (subtrai o valor)
        db.update_balance(telegram_id, -amount)
        new_balance = db.get_balance(telegram_id)
        
        await update.message.reply_text(
            f"✅ Despesa adicionada: R$ {amount:.2f} em *{category}*.\n"
            f"💰 Saldo atual: R$ {new_balance:.2f}",
            parse_mode="Markdown"
        )
    except ValueError:
        await update.message.reply_text("Valor inválido. Use ponto ou vírgula decimal. Ex: 25.50")
    except Exception as e:
        logger.error(f"Erro em add_expense: {e}")
        await update.message.reply_text("Ocorreu um erro inesperado.")

async def list_expenses(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mostra botões inline com os meses que têm despesas."""
    telegram_id = update.effective_user.id
    months = db.get_months_with_expenses(telegram_id)
    
    if not months:
        await update.message.reply_text("Você ainda não registrou nenhuma despesa.")
        return
    
    keyboard = []
    for year, month in months:
        month_name = datetime(year, month, 1).strftime("%B de %Y")
        callback_data = f"list_month_{year}_{month}"
        keyboard.append([InlineKeyboardButton(month_name, callback_data=callback_data)])
    
    keyboard.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancel")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "📅 *Escolha o mês para ver os gastos:*",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )

async def list_month_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback dos botões de mês – exibe todas as despesas do mês."""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    if data == "cancel":
        await query.edit_message_text("Operação cancelada.")
        return
    
    parts = data.split("_")
    year = int(parts[2])
    month = int(parts[3])
    
    telegram_id = query.from_user.id
    expenses = db.get_expenses_by_month(telegram_id, year, month)
    
    if not expenses:
        await query.edit_message_text(f"Nenhuma despesa encontrada para {datetime(year, month, 1).strftime('%B/%Y')}.")
        return
    
    msg = f"📋 *Gastos de {datetime(year, month, 1).strftime('%B/%Y')}* (total: {len(expenses)})\n\n"
    total_month = 0.0
    for exp in expenses:
        date_str = datetime.strptime(exp["expense_date"], "%Y-%m-%d").strftime("%d/%m")
        desc = f" – {exp['description']}" if exp.get('description') else ""
        msg += f"`{exp['id']}` • {date_str} • R$ {exp['amount']:.2f} – *{exp['category']}*{desc}\n"
        total_month += exp['amount']
    
    msg += f"\n💰 *Total do mês:* R$ {total_month:.2f}"
    
    if len(msg) > 4096:
        for i in range(0, len(msg), 4096):
            await query.message.reply_text(msg[i:i+4096], parse_mode="Markdown")
        await query.delete_message()
    else:
        await query.edit_message_text(msg, parse_mode="Markdown")

async def show_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    balance = db.get_balance(telegram_id)
    await update.message.reply_text(f"💰 *Seu saldo atual:* R$ {balance:.2f}", parse_mode="Markdown")

async def set_balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /setsaldo 500.00"""
    try:
        if not context.args:
            await update.message.reply_text("Uso: `/setsaldo valor`\nEx: `/setsaldo 1000.00`", parse_mode="Markdown")
            return
        amount = float(context.args[0].replace(",", "."))
        telegram_id = update.effective_user.id
        db.set_balance(telegram_id, amount)
        await update.message.reply_text(f"✅ Saldo definido para R$ {amount:.2f}", parse_mode="Markdown")
    except ValueError:
        await update.message.reply_text("Valor inválido. Use ponto ou vírgula decimal.")

async def summary_week(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    end_date = date.today()
    start_date = end_date - timedelta(days=7)
    total, by_cat = db.get_summary(telegram_id, start_date, end_date)
    await _send_summary(update, "últimos 7 dias", total, by_cat, start_date, end_date)

async def summary_month(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    today = date.today()
    start_date = today.replace(day=1)
    end_date = today
    total, by_cat = db.get_summary(telegram_id, start_date, end_date)
    await _send_summary(update, "mês atual", total, by_cat, start_date, end_date)

async def _send_summary(update: Update, periodo_desc: str, total: float, by_cat: dict, start_date: date, end_date: date):
    if total == 0:
        await update.message.reply_text(f"Nenhuma despesa registrada no {periodo_desc}.")
        return
    msg = f"📊 *Resumo do {periodo_desc}* ({start_date.strftime('%d/%m')} a {end_date.strftime('%d/%m/%Y')})\n"
    msg += f"💰 *Total:* R$ {total:.2f}\n\n*Por categoria:*\n"
    for cat, val in sorted(by_cat.items(), key=lambda x: x[1], reverse=True):
        msg += f"• {cat}: R$ {val:.2f}\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def delete_expense(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not context.args:
            await update.message.reply_text("Uso: `/delete ID`", parse_mode="Markdown")
            return
        expense_id = int(context.args[0])
        telegram_id = update.effective_user.id
        
        # Busca o valor da despesa para devolver ao saldo
        expenses = db.get_expenses(telegram_id, limit=100)
        expense_to_delete = next((e for e in expenses if e["id"] == expense_id), None)
        
        success = db.delete_expense(expense_id, telegram_id)
        if success:
            if expense_to_delete:
                db.update_balance(telegram_id, expense_to_delete["amount"])
                new_balance = db.get_balance(telegram_id)
                await update.message.reply_text(
                    f"✅ Despesa ID {expense_id} removida. R$ {expense_to_delete['amount']:.2f} retornados ao saldo.\n"
                    f"💰 Saldo atual: R$ {new_balance:.2f}"
                )
            else:
                await update.message.reply_text(f"✅ Despesa ID {expense_id} removida.")
        else:
            await update.message.reply_text(f"❌ Não foi possível remover. Verifique o ID ou se a despesa pertence a você.")
    except ValueError:
        await update.message.reply_text("O ID deve ser um número.")
    except Exception as e:
        logger.error(f"Erro em delete: {e}")
        await update.message.reply_text("Erro ao deletar.")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Trata mensagens de texto que não são comandos (botões customizados)."""
    text = update.message.text
    if text == "/add":
        await add_expense(update, context)
    elif text == "/list":
        await list_expenses(update, context)
    elif text == "/saldo":
        await show_balance(update, context)
    elif text == "/setsaldo":
        await set_balance_command(update, context)
    elif text == "/delete":
        await delete_expense(update, context)
    elif text == "/semana":
        await summary_week(update, context)
    elif text == "/mes":
        await summary_month(update, context)
    elif text == "/start":
        await start(update, context)
    else:
        # Se não for nenhum comando conhecido, ignora (evita poluição)
        pass

async def summary_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback para resumo via botões inline (semana/mês)."""
    query = update.callback_query
    await query.answer()
    if query.data == "summary_week":
        await summary_week(update, context)
        await query.delete_message()
    elif query.data == "summary_month":
        await summary_month(update, context)
        await query.delete_message()
async def cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Operação cancelada.")

# ==================== CONFIGURAÇÃO DO BOT E WEBHOOK ====================

# Cria a aplicação do Telegram
application = Application.builder().token(TOKEN).build()

# Adiciona todos os handlers
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("add", add_expense))
application.add_handler(CommandHandler("list", list_expenses))
application.add_handler(CommandHandler("saldo", show_balance))
application.add_handler(CommandHandler("setsaldo", set_balance_command))
application.add_handler(CommandHandler("semana", summary_week))
application.add_handler(CommandHandler("mes", summary_month))
application.add_handler(CommandHandler("delete", delete_expense))
application.add_handler(CallbackQueryHandler(list_month_callback, pattern="^list_month_"))
application.add_handler(CallbackQueryHandler(summary_callback, pattern="^summary_"))
application.add_handler(CallbackQueryHandler(lambda u, c: u.callback_query.answer(), pattern="cancel"))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

# ==================== SERVIDOR FASTAPI PARA WEBHOOK ====================

app = FastAPI()

@app.post("/webhook")
async def webhook(request: Request):
    """Recebe atualizações do Telegram via webhook."""
    data = await request.json()
    update = Update.de_json(data, application.bot)
    await application.process_update(update)
    return {"status": "ok"}

@app.get("/health")
async def health():
    """Endpoint de saúde para o Render (keep-alive)."""
    return {"status": "ok"}
    
@app.get("/")
async def root():
    return {"status": "ok"}

async def setup_webhook():
    """Configura o webhook no Telegram ao iniciar o servidor."""
    webhook_url = f"{WEBHOOK_URL}/webhook"
    await application.bot.set_webhook(webhook_url, drop_pending_updates=True)
    logger.info(f"Webhook configurado para {webhook_url}")

@app.on_event("startup")
async def startup_event():
    await application.initialize()
    """Executado quando o FastAPI inicia no Render."""
    await setup_webhook()
    logger.info("Bot rodando com webhook!")

# ==================== PONTO DE ENTRADA ====================
if __name__ == "__main__":
    # Se a variável RENDER_EXTERNAL_URL existir, estamos no Render → webhook
    if WEBHOOK_URL:
        logger.info(f"Iniciando servidor webhook na porta {PORT}")
        uvicorn.run(app, host="0.0.0.0", port=PORT)
    else:
        # Caso contrário, roda localmente com polling
        logger.info("Rodando localmente com polling...")
        application.run_polling(allowed_updates=Update.ALL_TYPES)

import os
from supabase import create_client, Client
from datetime import datetime, date
from dotenv import load_dotenv

load_dotenv()

url: str = os.getenv("SUPABASE_URL")
key: str = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(url, key)

def add_expense(telegram_id: int, amount: float, category: str, description: str = "", expense_date: date = None):
    """Insere uma nova despesa no banco."""
    if expense_date is None:
        expense_date = date.today()
    data = {
        "telegram_id": telegram_id,
        "amount": amount,
        "category": category,
        "description": description,
        "expense_date": expense_date.isoformat()
    }
    response = supabase.table("expenses").insert(data).execute()
    return response.data[0] if response.data else None

def get_expenses(telegram_id: int, limit: int = 10):
    """Retorna as últimas 'limit' despesas do usuário, ordenadas por data decrescente."""
    response = supabase.table("expenses") \
        .select("*") \
        .eq("telegram_id", telegram_id) \
        .order("expense_date", desc=True) \
        .order("created_at", desc=True) \
        .limit(limit) \
        .execute()
    return response.data

def get_summary(telegram_id: int, start_date: date, end_date: date):
    """Retorna o total gasto e um resumo por categoria num período."""
    # Busca todas as despesas no período
    response = supabase.table("expenses") \
        .select("amount, category") \
        .eq("telegram_id", telegram_id) \
        .gte("expense_date", start_date.isoformat()) \
        .lte("expense_date", end_date.isoformat()) \
        .execute()
    
    expenses = response.data
    total = sum(e["amount"] for e in expenses)
    # Agrupa por categoria
    by_category = {}
    for e in expenses:
        cat = e["category"]
        by_category[cat] = by_category.get(cat, 0) + e["amount"]
    return total, by_category

def delete_expense(expense_id: int, telegram_id: int) -> bool:
    """Remove uma despesa se ela pertencer ao usuário."""
    response = supabase.table("expenses") \
        .delete() \
        .eq("id", expense_id) \
        .eq("telegram_id", telegram_id) \
        .execute()
    # Se retornou dados, foi deletado com sucesso
    return len(response.data) > 0

# ===== NOVAS FUNÇÕES PARA SALDO =====

def get_balance(telegram_id: int) -> float:
    """Retorna o saldo atual do usuário (0 se não existir ou erro)."""
    try:
        response = supabase.table("user_balance") \
            .select("balance") \
            .eq("telegram_id", telegram_id) \
            .limit(1) \
            .execute()

        if response and response.data:
            return float(response.data[0]["balance"])
        return 0.0
    except Exception as e:
        print(f"Erro ao buscar saldo: {e}")
        return 0.0

def set_balance(telegram_id: int, new_balance: float) -> bool:
    """Define o saldo do usuário. Se não existir, insere."""
    try:
        data = {"telegram_id": telegram_id, "balance": new_balance}
        response = supabase.table("user_balance").upsert(data, on_conflict="telegram_id").execute()
        return response is not None and len(response.data) > 0
    except Exception as e:
        print(f"Erro ao definir saldo: {e}")
        return False

def update_balance(telegram_id: int, delta: float) -> bool:
    """Ajusta o saldo somando delta (positivo ou negativo)."""
    current = get_balance(telegram_id)
    new_balance = current + delta
    return set_balance(telegram_id, new_balance)

# ===== FUNÇÕES DE DESPESAS MODIFICADAS =====

def get_expenses_by_month(telegram_id: int, year: int, month: int):
    """Retorna todas as despesas de um mês específico (sem limite)."""
    start_date = f"{year}-{month:02d}-01"
    # Calcula o último dia do mês
    if month == 12:
        end_date = f"{year+1}-01-01"
    else:
        end_date = f"{year}-{month+1:02d}-01"
    
    response = supabase.table("expenses") \
        .select("*") \
        .eq("telegram_id", telegram_id) \
        .gte("expense_date", start_date) \
        .lt("expense_date", end_date) \
        .order("expense_date", desc=True) \
        .execute()
    return response.data

def get_months_with_expenses(telegram_id: int, limit_months: int = 12):
    """Retorna lista de tuplas (ano, mês) que possuem despesas, dos mais recentes."""
    # Busca todas as despesas do usuário, pega apenas as datas distintas
    response = supabase.table("expenses") \
        .select("expense_date") \
        .eq("telegram_id", telegram_id) \
        .order("expense_date", desc=True) \
        .execute()
    
    months = set()
    for item in response.data:
        d = datetime.strptime(item["expense_date"], "%Y-%m-%d")
        months.add((d.year, d.month))
    
    # Ordena do mais recente para o mais antigo
    sorted_months = sorted(list(months), key=lambda x: (x[0], x[1]), reverse=True)
    return sorted_months[:limit_months]
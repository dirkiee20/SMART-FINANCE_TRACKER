from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
from functools import wraps
import json
import os
import random
import calendar

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_secret_key'
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'mysql+pymysql://root:@localhost/finance_tracker')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)
migrate = Migrate(app, db)

# Login required decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    transactions = db.relationship('Transaction', backref='user', lazy=True)
    budgets = db.relationship('Budget', backref='user', lazy=True)
    goals = db.relationship('Goal', backref='user', lazy=True)
    email_notifications = db.Column(db.Boolean, default=True)
    budget_alerts = db.Column(db.Boolean, default=True)
    goal_updates = db.Column(db.Boolean, default=True)

    def __init__(self, username, email, password):
        self.username = username
        self.email = email
        self.password = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password, password)

class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    amount = db.Column(db.Float, nullable=False)
    category = db.Column(db.String(50), nullable=False)
    type = db.Column(db.String(10), nullable=False)  # 'income' or 'expense'
    date = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

class Goal(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    target_amount = db.Column(db.Float, nullable=False)
    current_amount = db.Column(db.Float, default=0)
    target_date = db.Column(db.DateTime, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

class Budget(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(50), nullable=False)
    limit = db.Column(db.Float, nullable=False)  # Changed from 'amount' to 'limit'
    spent = db.Column(db.Float, default=0)
    month = db.Column(db.DateTime, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

class Debt(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    type = db.Column(db.String(50), nullable=False)  # 'credit_card', 'loan', 'mortgage', etc.
    balance = db.Column(db.Float, nullable=False)
    original_amount = db.Column(db.Float, nullable=False)
    interest_rate = db.Column(db.Float, nullable=False)
    minimum_payment = db.Column(db.Float, nullable=False)
    next_payment_date = db.Column(db.DateTime, nullable=False)
    paid_amount = db.Column(db.Float, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

def get_spending_warnings(user_id):
    """Calculate spending warnings based on user's transaction patterns"""
    warnings = []
    
    # Get current month's transactions
    current_month = datetime.now().replace(day=1)
    monthly_transactions = Transaction.query.filter_by(
        user_id=user_id,
        type='expense'
    ).filter(Transaction.date >= current_month).all()
    
    # Get user's budgets
    budgets = Budget.query.filter_by(user_id=user_id).all()
    
    # Check for overspending in budget categories
    for budget in budgets:
        spent = sum(t.amount for t in monthly_transactions if t.category == budget.category)
        if spent > budget.limit:
            warnings.append({
                'type': 'budget_exceeded',
                'category': budget.category,
                'message': f'You have exceeded your {budget.category} budget by ${spent - budget.limit:.2f}',
                'severity': 'high'
            })
        elif spent > budget.limit * 0.8:  # Warning at 80% of budget
            warnings.append({
                'type': 'budget_warning',
                'category': budget.category,
                'message': f'You are close to exceeding your {budget.category} budget (${budget.limit - spent:.2f} remaining)',
                'severity': 'medium'
            })
    
    # Check for unusual spending patterns
    category_totals = {}
    for transaction in monthly_transactions:
        category_totals[transaction.category] = category_totals.get(transaction.category, 0) + transaction.amount
    
    # Get average spending for each category from previous months
    for category in category_totals:
        prev_months_avg = db.session.query(db.func.avg(Transaction.amount)).filter(
            Transaction.user_id == user_id,
            Transaction.category == category,
            Transaction.type == 'expense',
            Transaction.date < current_month
        ).scalar() or 0
        
        if category_totals[category] > prev_months_avg * 1.5:  # 50% increase
            warnings.append({
                'type': 'spending_increase',
                'category': category,
                'message': f'Unusual increase in {category} spending this month',
                'severity': 'medium'
            })
    
    return warnings

def get_savings_advice(user_id):
    """Generate personalized savings advice based on user's financial data"""
    advice = []
    
    # Get user's goals and current savings
    goals = Goal.query.filter_by(user_id=user_id).all()
    total_savings = sum(goal.current_amount for goal in goals)
    total_goals = sum(goal.target_amount for goal in goals)
    
    # Get monthly income and expenses
    current_month = datetime.now().replace(day=1)
    monthly_income = db.session.query(db.func.sum(Transaction.amount)).filter(
        Transaction.user_id == user_id,
        Transaction.type == 'income',
        Transaction.date >= current_month
    ).scalar() or 0
    
    monthly_expenses = db.session.query(db.func.sum(Transaction.amount)).filter(
        Transaction.user_id == user_id,
        Transaction.type == 'expense',
        Transaction.date >= current_month
    ).scalar() or 0
    
    # Calculate savings rate
    if monthly_income > 0:
        savings_rate = (monthly_income - monthly_expenses) / monthly_income * 100
    else:
        savings_rate = 0
    
    # Generate advice based on savings rate
    if savings_rate < 20:
        advice.append({
            'type': 'savings_rate',
            'message': 'Your savings rate is below the recommended 20%. Consider reducing non-essential expenses.',
            'priority': 'high'
        })
    elif savings_rate > 50:
        advice.append({
            'type': 'savings_rate',
            'message': 'Great job! Your high savings rate puts you on track for financial independence.',
            'priority': 'low'
        })
    
    # Check progress towards goals
    for goal in goals:
        progress = (goal.current_amount / goal.target_amount) * 100
        months_remaining = (goal.target_date - datetime.now()).days / 30
        
        if months_remaining > 0:
            required_monthly = (goal.target_amount - goal.current_amount) / months_remaining
            
            if required_monthly > (monthly_income - monthly_expenses):
                advice.append({
                    'type': 'goal_progress',
                    'message': f'To reach your {goal.name} goal, you need to save ${required_monthly:.2f} monthly',
                    'priority': 'medium'
                })
    
    return advice

def get_budget_tips(user_id):
    """Generate personalized budget tips based on spending patterns"""
    tips = []
    
    # Get spending patterns for the last 3 months
    three_months_ago = datetime.now().replace(day=1) - timedelta(days=90)
    recent_transactions = Transaction.query.filter_by(
        user_id=user_id,
        type='expense'
    ).filter(Transaction.date >= three_months_ago).all()
    
    # Analyze category spending
    category_totals = {}
    for transaction in recent_transactions:
        category_totals[transaction.category] = category_totals.get(transaction.category, 0) + transaction.amount
    
    # Identify highest spending categories
    sorted_categories = sorted(category_totals.items(), key=lambda x: x[1], reverse=True)
    
    # Generate tips based on spending patterns
    for category, amount in sorted_categories[:3]:  # Top 3 spending categories
        if category in ['Dining', 'Entertainment', 'Shopping']:
            tips.append({
                'category': category,
                'message': f'Consider reducing {category.lower()} expenses by setting a weekly limit',
                'suggestion': 'Try meal prepping or finding free entertainment options'
            })
        elif category in ['Transportation', 'Bills']:
            tips.append({
                'category': category,
                'message': f'Look for ways to optimize your {category.lower()} expenses',
                'suggestion': 'Compare service providers or consider carpooling'
            })
    
    # Add general budget tips
    tips.append({
        'category': 'General',
        'message': 'Review your subscriptions and recurring payments',
        'suggestion': 'Cancel unused subscriptions to save money'
    })
    
    return tips

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user = User.query.get(session['user_id'])
    transactions = Transaction.query.filter_by(user_id=session['user_id']).order_by(Transaction.date.desc()).limit(5).all()
    
    # Calculate totals and insights
    all_transactions = Transaction.query.filter_by(user_id=session['user_id']).all()
    total_income = sum(t.amount for t in all_transactions if t.type == 'income')
    total_expenses = sum(t.amount for t in all_transactions if t.type == 'expense')
    balance = total_income - total_expenses
    
    # Get biggest expense and highest income
    biggest_expense = Transaction.query.filter_by(user_id=session['user_id'], type='expense').order_by(Transaction.amount.desc()).first()
    highest_income = Transaction.query.filter_by(user_id=session['user_id'], type='income').order_by(Transaction.amount.desc()).first()
    
    # Get spending by category for the current month
    current_month = datetime.now().replace(day=1)
    expense_categories = {}
    monthly_transactions = Transaction.query.filter_by(user_id=session['user_id']).filter(
        Transaction.date >= current_month
    ).all()
    
    for t in monthly_transactions:
        if t.type == 'expense':
            expense_categories[t.category] = expense_categories.get(t.category, 0) + t.amount
    
    # Spending Analysis
    spending_analysis = {
        'monthly_trend': {},
        'category_trends': {},
        'spending_patterns': []
    }
    
    # Calculate monthly spending trends for the last 6 months
    for i in range(6):
        month = (current_month - timedelta(days=30*i)).replace(day=1)
        month_transactions = Transaction.query.filter_by(user_id=session['user_id']).filter(
            Transaction.date >= month,
            Transaction.date < (month + timedelta(days=32)).replace(day=1)
        ).all()
        
        month_expenses = sum(t.amount for t in month_transactions if t.type == 'expense')
        month_income = sum(t.amount for t in month_transactions if t.type == 'income')
        
        spending_analysis['monthly_trend'][month.strftime('%Y-%m')] = {
            'expenses': month_expenses,
            'income': month_income,
            'savings_rate': ((month_income - month_expenses) / month_income * 100) if month_income > 0 else 0
        }
    
    # Calculate category trends
    for category in expense_categories.keys():
        category_trend = []
        for i in range(6):
            month = (current_month - timedelta(days=30*i)).replace(day=1)
            month_amount = sum(t.amount for t in monthly_transactions 
                             if t.category == category and t.date >= month and t.date < (month + timedelta(days=32)).replace(day=1))
            category_trend.append(month_amount)
        spending_analysis['category_trends'][category] = category_trend
    
    # Identify spending patterns
    if expense_categories:
        avg_monthly_spending = sum(expense_categories.values()) / len(expense_categories)
        for category, amount in expense_categories.items():
            if amount > avg_monthly_spending * 1.5:
                spending_analysis['spending_patterns'].append({
                    'category': category,
                    'amount': amount,
                    'message': f'High spending in {category} category'
                })
    
    # Cashflow Forecasting
    cashflow_forecast = {
        'next_month': {
            'projected_income': total_income,  # Assuming stable income
            'projected_expenses': total_expenses,  # Assuming stable expenses
            'projected_balance': balance
        },
        'three_months': {
            'projected_income': total_income * 3,
            'projected_expenses': total_expenses * 3,
            'projected_balance': balance * 3
        },
        'six_months': {
            'projected_income': total_income * 6,
            'projected_expenses': total_expenses * 6,
            'projected_balance': balance * 6
        }
    }
    
    # Add trend-based adjustments to forecasts
    if len(spending_analysis['monthly_trend']) >= 2:
        recent_months = list(spending_analysis['monthly_trend'].values())[:2]
        expense_trend = recent_months[0]['expenses'] - recent_months[1]['expenses']
        income_trend = recent_months[0]['income'] - recent_months[1]['income']
        
        # Adjust forecasts based on trends
        for period in ['next_month', 'three_months', 'six_months']:
            months = 1 if period == 'next_month' else (3 if period == 'three_months' else 6)
            cashflow_forecast[period]['projected_expenses'] += expense_trend * months
            cashflow_forecast[period]['projected_income'] += income_trend * months
            cashflow_forecast[period]['projected_balance'] = (
                cashflow_forecast[period]['projected_income'] - 
                cashflow_forecast[period]['projected_expenses']
            )
    
    # Check budget status
    budget_alert = None
    if total_expenses > total_income:
        budget_alert = "Warning: You're over budget!"
    
    # Add budget status
    budget_status = {
        'type': 'warning' if total_expenses > total_income else 'success',
        'icon': 'exclamation-triangle' if total_expenses > total_income else 'check-circle',
        'title': 'Budget Alert' if total_expenses > total_income else 'Budget Status',
        'message': 'You are currently over budget!' if total_expenses > total_income else 'You are within budget!'
    }
    
    # Get savings goals
    savings_goals = Goal.query.filter_by(user_id=session['user_id']).all()
    
    # Generate AI insights
    ai_insights = [
        {
            'icon': 'piggy-bank',
            'message': f'Based on your current savings rate, you could save ${balance * 12:.2f} annually.'
        },
        {
            'icon': 'lightbulb',
            'message': 'Try the 50/30/20 rule: 50% needs, 30% wants, 20% savings.'
        }
    ]
    
    # Add spending insight only if there are expense categories
    if expense_categories:
        ai_insights.insert(0, {
            'icon': 'chart-line',
            'message': f'Your spending in {max(expense_categories, key=expense_categories.get)} '
                      f'category is higher than usual. Consider setting a budget.'
        })
    
    # Prepare daily data for the trend chart
    daily_data = {}
    for transaction in all_transactions:
        day_key = transaction.date.strftime('%Y-%m-%d')
        if day_key not in daily_data:
            daily_data[day_key] = {'income': 0, 'expense': 0}
        daily_data[day_key][transaction.type] += transaction.amount
    
    # Sort daily data by date
    daily_data = dict(sorted(daily_data.items()))
    
    # Get current month's budgets
    budgets = Budget.query.filter_by(
        user_id=session['user_id'],
        month=current_month
    ).all()
    
    # Calculate spent amounts for each budget
    for budget in budgets:
        spent = Transaction.query.filter_by(
            user_id=session['user_id'],
            category=budget.category,
            type='expense'
        ).filter(
            Transaction.date >= budget.month,
            Transaction.date < budget.month.replace(month=budget.month.month + 1)
        ).with_entities(db.func.sum(Transaction.amount)).scalar() or 0
        
        budget.spent = spent

    # Get user's debts
    debts = Debt.query.filter_by(user_id=session['user_id']).all()
    
    # Get new insights
    spending_warnings = get_spending_warnings(session['user_id'])
    savings_advice = get_savings_advice(session['user_id'])
    budget_tips = get_budget_tips(session['user_id'])
    
    return render_template('dashboard.html',
                         user=user,
                         transactions=transactions,
                         income=total_income,
                         expenses=total_expenses,
                         savings=balance,
                         biggest_expense=biggest_expense,
                         highest_income=highest_income,
                         expense_categories=expense_categories,
                         budget_status=budget_status,
                         savings_goals=savings_goals,
                         ai_insights=ai_insights,
                         daily_data=daily_data,
                         budgets=budgets,
                         debts=debts,
                         spending_analysis=spending_analysis,
                         cashflow_forecast=cashflow_forecast,
                         spending_warnings=spending_warnings,
                         savings_advice=savings_advice,
                         budget_tips=budget_tips)

# Add a redirect from root to dashboard
@app.route('/')
def index():
    return redirect(url_for('dashboard'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        
        if not username or not password:
            flash('Please enter both username and password', 'warning')
            return render_template('login.html')
        
        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password):
            session['user_id'] = user.id
            flash('Welcome back!', 'success')
            return redirect(url_for('dashboard'))
        
        flash('Invalid username or password. Please try again.', 'danger')
        return render_template('login.html')
    
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()
        
        # Validate input
        if not username or not email or not password:
            flash('Please fill in all fields', 'warning')
            return redirect(url_for('register'))
        
        # Check if username already exists
        if User.query.filter_by(username=username).first():
            flash('Username already exists', 'danger')
            return redirect(url_for('register'))
        
        # Check if email already exists
        if User.query.filter_by(email=email).first():
            flash('Email already registered', 'danger')
            return redirect(url_for('register'))
        
        try:
            # Create new user
            user = User(username=username, email=email, password=password)
            db.session.add(user)
            db.session.commit()
            flash('Registration successful! Please login.', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            db.session.rollback()
            flash('An error occurred during registration. Please try again.', 'danger')
            return redirect(url_for('register'))
    
    return render_template('register.html')

@app.route('/transactions')
def transactions():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    transactions = Transaction.query.filter_by(user_id=session['user_id']).order_by(Transaction.date.desc()).all()
    goals = Goal.query.filter_by(user_id=session['user_id']).all()
    return render_template('transactions.html', transactions=transactions, goals=goals)

@app.route('/add_transaction', methods=['POST'])
@login_required
def add_transaction():
    amount = float(request.form.get('amount', 0))
    category = request.form.get('category')
    type = request.form.get('type')
    goal_id = request.form.get('goal_id')
    
    # Create new transaction
    transaction = Transaction(
        amount=amount,
        category=category,
        type=type,
        date=datetime.now(),
        user_id=session['user_id']
    )
    
    # If this is a goal contribution
    if goal_id and type == 'income':
        goal = Goal.query.get(goal_id)
        if goal and goal.user_id == session['user_id']:
            goal.current_amount += amount
            transaction.note = f"Contribution to goal: {goal.name}"
    
    # Update budget spent amount if it's an expense
    if type == 'expense':
        current_month = datetime.now().replace(day=1)
        budget = Budget.query.filter_by(
            user_id=session['user_id'],
            category=category,
            month=current_month
        ).first()
        
        if budget:
            budget.spent = (budget.spent or 0) + amount
    
    db.session.add(transaction)
    db.session.commit()
    
    flash('Transaction added successfully!', 'success')
    return redirect(url_for('transactions'))

@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        username = request.form['username']
        new_password = request.form['new_password']
        user = User.query.filter_by(username=username).first()
        
        if user:
            user.password = generate_password_hash(new_password)
            db.session.commit()
            flash('Password has been reset successfully')
            return redirect(url_for('login'))
        flash('Username not found')
    return render_template('forgot_password.html')

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('login'))

@app.route('/reports')
def reports():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    transactions = Transaction.query.filter_by(user_id=session['user_id']).all()
    
    # Calculate current month's totals
    current_month_year = datetime.now().strftime('%Y-%m')
    monthly_income = 0.0
    monthly_expenses = 0.0

    # Filter transactions for the current month and aggregate daily
    daily_data = {}
    transactions_current_month = [t for t in transactions if t.date.strftime('%Y-%m') == current_month_year]

    for transaction in transactions_current_month:
        day_key = transaction.date.strftime('%Y-%m-%d')
        if day_key not in daily_data:
            daily_data[day_key] = {'income': 0.0, 'expense': 0.0}
        daily_data[day_key][transaction.type] += float(transaction.amount)

        if transaction.type == 'income':
            monthly_income += float(transaction.amount)
        else:
            monthly_expenses += float(transaction.amount)

    # Generate all days in the current month for labels
    year, month = map(int, current_month_year.split('-'))
    num_days = calendar.monthrange(year, month)[1]
    daily_labels = [f'{year}-{month:02d}-{day:02d}' for day in range(1, num_days + 1)]

    # Prepare daily income and expense data, filling in 0 for days with no transactions
    daily_income_data = [daily_data.get(day, {'income': 0.0})['income'] for day in daily_labels]
    daily_expense_data = [daily_data.get(day, {'expense': 0.0})['expense'] for day in daily_labels]

    monthly_savings = monthly_income - monthly_expenses

    # Calculate category breakdown for current month
    category_breakdown = []
    category_totals = {}

    for transaction in transactions_current_month: # Use current month transactions
        if transaction.type == 'expense':
            category_totals[transaction.category] = category_totals.get(transaction.category, 0.0) + float(transaction.amount)

    total_expenses = sum(category_totals.values())

    for category, amount in category_totals.items():
        percentage = (amount / total_expenses * 100) if total_expenses > 0 else 0.0
        category_breakdown.append({
            'name': str(category),
            'amount': float(amount),
            'percentage': float(percentage)
        })

    # Sort category breakdown by amount
    category_breakdown.sort(key=lambda x: x['amount'], reverse=True)

    # Prepare data for category chart
    category_labels = [str(item['name']) for item in category_breakdown]
    category_data = [float(item['amount']) for item in category_breakdown]

    # Get current month and year for display
    current_month_name = datetime.now().strftime('%B')
    current_year = datetime.now().strftime('%Y')
    month_year_label = f'{current_month_name} {current_year}'

    return render_template('reports.html',
                         daily_labels=daily_labels,
                         daily_income_data=daily_income_data,
                         daily_expense_data=daily_expense_data,
                         monthly_income=monthly_income,
                         monthly_expenses=monthly_expenses,
                         monthly_savings=monthly_savings,
                         category_breakdown=category_breakdown,
                         category_labels=category_labels,
                         category_data=category_data,
                         month_year_label=month_year_label)

@app.route('/goals')
@login_required
def goals():
    goals = Goal.query.filter_by(user_id=session['user_id']).all()
    now = datetime.now()
    return render_template('goals.html', goals=goals, now=now)

@app.route('/add_goal', methods=['POST'])
@login_required
def add_goal():
    name = request.form.get('name')
    target_amount = float(request.form.get('target_amount'))
    target_date = datetime.strptime(request.form.get('target_date'), '%Y-%m-%d')
    
    new_goal = Goal(
        name=name,
        target_amount=target_amount,
        current_amount=0.0,
        target_date=target_date,
        user_id=session['user_id']
    )
    
    db.session.add(new_goal)
    db.session.commit()
    flash('Goal added successfully!', 'success')
    return redirect(url_for('goals'))

@app.route('/update_goal/<int:goal_id>', methods=['POST'])
@login_required
def update_goal(goal_id):
    goal = Goal.query.get_or_404(goal_id)
    if goal.user_id != session['user_id']:
        abort(403)
    
    current_amount = float(request.form.get('current_amount'))
    goal.current_amount = current_amount
    db.session.commit()
    flash('Goal progress updated!', 'success')
    return redirect(url_for('goals'))

@app.route('/delete_goal/<int:goal_id>', methods=['POST'])
@login_required
def delete_goal(goal_id):
    goal = Goal.query.get_or_404(goal_id)
    if goal.user_id != session['user_id']:
        abort(403)
    
    db.session.delete(goal)
    db.session.commit()
    flash('Goal deleted successfully!', 'success')
    return redirect(url_for('goals'))

@app.route('/budget')
@login_required
def budget():
    # Get all budget categories for the current user
    categories = Budget.query.filter_by(user_id=session['user_id']).all()
    
    # Calculate spent amounts for each budget category
    for category in categories:
        spent = Transaction.query.filter_by(
            user_id=session['user_id'],
            category=category.category,
            type='expense'
        ).filter(
            Transaction.date >= category.month,
            Transaction.date < category.month.replace(month=category.month.month + 1)
        ).with_entities(db.func.sum(Transaction.amount)).scalar() or 0
        
        category.spent = spent
    
    # Calculate totals with safe handling of None values
    total_budget = sum(category.limit or 0 for category in categories)
    total_spent = sum(category.spent or 0 for category in categories)
    remaining_budget = total_budget - total_spent
    
    # Prepare data for the chart
    category_names = [category.category for category in categories]
    budget_amounts = [float(category.limit or 0) for category in categories]
    spent_amounts = [float(category.spent or 0) for category in categories]
    
    return render_template('budget.html',
                         categories=categories,
                         total_budget=total_budget,
                         total_spent=total_spent,
                         remaining_budget=remaining_budget,
                         category_names=category_names,
                         budget_amounts=budget_amounts,
                         spent_amounts=spent_amounts)

@app.route('/add_budget_category', methods=['POST'])
@login_required
def add_budget_category():
    category = request.form.get('category')
    limit = float(request.form.get('limit', 0))
    
    new_category = Budget(
        category=category,
        limit=limit,
        spent=0.0,
        month=datetime.now().replace(day=1),
        user_id=session['user_id']
    )
    
    db.session.add(new_category)
    db.session.commit()
    flash('Budget category added successfully!', 'success')
    return redirect(url_for('budget'))

@app.route('/update_budget_category/<int:category_id>', methods=['POST'])
@login_required
def update_budget_category(category_id):
    category = Budget.query.get_or_404(category_id)
    if category.user_id != session['user_id']:
        abort(403)
    
    budget = float(request.form.get('budget'))
    category.budget = budget
    db.session.commit()
    flash('Budget category updated!', 'success')
    return redirect(url_for('budget'))

@app.route('/delete_budget_category/<int:category_id>', methods=['POST'])
@login_required
def delete_budget_category(category_id):
    category = Budget.query.get_or_404(category_id)
    if category.user_id != session['user_id']:
        abort(403)
    
    db.session.delete(category)
    db.session.commit()
    flash('Budget category deleted successfully!', 'success')
    return redirect(url_for('budget'))

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if request.method == 'POST':
        # Get the current user
        user = User.query.get(session['user_id'])
        
        # Handle profile update
        if 'username' in request.form:
            user.username = request.form['username']
            user.email = request.form['email']
            db.session.commit()
            flash('Profile updated successfully!', 'success')
            return redirect(url_for('settings'))
        
        # Handle password update
        elif 'current_password' in request.form:
            current_password = request.form['current_password']
            new_password = request.form['new_password']
            confirm_password = request.form['confirm_password']
            
            if not check_password_hash(user.password, current_password):
                flash('Current password is incorrect!', 'danger')
                return redirect(url_for('settings'))
            
            if new_password != confirm_password:
                flash('New passwords do not match!', 'danger')
                return redirect(url_for('settings'))
            
            user.password = generate_password_hash(new_password)
            db.session.commit()
            flash('Password updated successfully!', 'success')
            return redirect(url_for('settings'))
        
        # Handle notification preferences
        elif 'email_notifications' in request.form:
            # Update notification preferences
            user.email_notifications = 'email_notifications' in request.form
            user.budget_alerts = 'budget_alerts' in request.form
            user.goal_updates = 'goal_updates' in request.form
            db.session.commit()
            flash('Notification preferences updated!', 'success')
            return redirect(url_for('settings'))
    
    # Get the current user for the template
    user = User.query.get(session['user_id'])
    return render_template('settings.html', user=user)

@app.route('/ai_query', methods=['POST'])
def ai_query():
    if 'user_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
        
    query = request.json.get('query')
    
    # Get user's financial data
    user_id = session['user_id']
    
    # Get recent transactions
    recent_transactions = Transaction.query.filter_by(user_id=user_id)\
        .order_by(Transaction.date.desc())\
        .limit(10).all()
    
    # Get savings goals
    savings_goals = Goal.query.filter_by(user_id=user_id).all()
    
    # Get current month's budgets
    current_month = datetime.now().replace(day=1)
    budgets = Budget.query.filter_by(
        user_id=user_id,
        month=current_month
    ).all()
    
    # Get debts
    debts = Debt.query.filter_by(user_id=user_id).all()
    
    # Calculate total income and expenses
    total_income = sum(t.amount for t in recent_transactions if t.type == 'income')
    total_expenses = sum(t.amount for t in recent_transactions if t.type == 'expense')
    
    # Prepare context for AI
    context = {
        'recent_transactions': [
            {
                'date': t.date.strftime('%Y-%m-%d'),
                'category': t.category,
                'type': t.type,
                'amount': float(t.amount)
            } for t in recent_transactions
        ],
        'savings_goals': [
            {
                'name': g.name,
                'target_amount': float(g.target_amount),
                'current_amount': float(g.current_amount),
                'target_date': g.target_date.strftime('%Y-%m-%d')
            } for g in savings_goals
        ],
        'budgets': [
            {
                'category': b.category,
                'amount': float(b.amount),
                'spent': float(b.spent) if hasattr(b, 'spent') else 0
            } for b in budgets
        ],
        'debts': [
            {
                'name': d.name,
                'balance': float(d.balance),
                'interest_rate': float(d.interest_rate),
                'minimum_payment': float(d.minimum_payment)
            } for d in debts
        ],
        'summary': {
            'total_income': float(total_income),
            'total_expenses': float(total_expenses),
            'net_balance': float(total_income - total_expenses)
        }
    }
    
    # Generate response based on query and context
    response = generate_ai_response(query, context)
    
    return jsonify({
        'response': response
    })

def generate_ai_response(query, context):
    query = query.lower()
    
    # Check for spending-related questions
    if any(word in query for word in ['spend', 'expense', 'cost', 'money']):
        if context['summary']['total_expenses'] > context['summary']['total_income']:
            return f"Your expenses (${context['summary']['total_expenses']:.2f}) are higher than your income (${context['summary']['total_income']:.2f}). Consider reviewing your spending habits."
        else:
            return f"Your spending looks healthy! You've spent ${context['summary']['total_expenses']:.2f} out of ${context['summary']['total_income']:.2f} income."
    
    # Check for savings-related questions
    elif any(word in query for word in ['save', 'savings', 'goal']):
        if context['savings_goals']:
            goals_status = []
            for goal in context['savings_goals']:
                progress = (goal['current_amount'] / goal['target_amount']) * 100
                goals_status.append(f"{goal['name']}: {progress:.1f}% complete")
            return f"Your savings goals:\n" + "\n".join(goals_status)
        else:
            return "You haven't set any savings goals yet. Consider setting some to help track your progress!"
    
    # Check for budget-related questions
    elif any(word in query for word in ['budget', 'limit']):
        if context['budgets']:
            budget_status = []
            for budget in context['budgets']:
                usage = (budget['spent'] / budget['amount']) * 100
                status = "over" if usage > 100 else "under"
                budget_status.append(f"{budget['category']}: {usage:.1f}% of budget ({status})")
            return "Your budget status:\n" + "\n".join(budget_status)
        else:
            return "You haven't set any budgets yet. Setting budgets can help you manage your spending better!"
    
    # Check for debt-related questions
    elif any(word in query for word in ['debt', 'loan', 'credit']):
        if context['debts']:
            total_debt = sum(d['balance'] for d in context['debts'])
            return f"You have {len(context['debts'])} active debts totaling ${total_debt:.2f}. Consider focusing on paying off high-interest debts first."
        else:
            return "You don't have any active debts recorded. That's great!"
    
    # Default response
    return "I can help you analyze your spending, savings goals, budgets, and debts. What would you like to know about?"

def create_test_user():
    try:
        test_user = User.query.filter_by(username='test').first()
        if not test_user:
            test_user = User(username='test', email='test@example.com', password='test123')
            db.session.add(test_user)
            db.session.commit()
            print("Test user created successfully! Username: test, Password: test123")
        else:
            print("Test user already exists")
    except Exception as e:
        print(f"Error creating test user: {e}")
        db.session.rollback()

def create_test_data():
    try:
        test_user = User.query.filter_by(username='test').first()
        if not test_user:
            print("Test user not found. Please create test user first.")
            return

        # Create sample transactions for the last 30 days
        from datetime import datetime, timedelta
        import random

        # Sample categories
        expense_categories = ['Groceries', 'Dining', 'Transportation', 'Entertainment', 'Shopping', 'Bills']
        income_categories = ['Salary', 'Freelance', 'Investments', 'Gifts']

        # Create transactions for the last 30 days
        for i in range(30):
            date = datetime.now() - timedelta(days=i)
            
            # Create 1-3 transactions per day
            for _ in range(random.randint(1, 3)):
                # Create expense
                expense = Transaction(
                    amount=round(random.uniform(10, 200), 2),
                    category=random.choice(expense_categories),
                    type='expense',
                    date=date,
                    user_id=test_user.id
                )
                db.session.add(expense)

                # Create income (less frequent)
                if random.random() < 0.3:  # 30% chance of income
                    income = Transaction(
                        amount=round(random.uniform(100, 1000), 2),
                        category=random.choice(income_categories),
                        type='income',
                        date=date,
                        user_id=test_user.id
                    )
                    db.session.add(income)

        # Create sample goals
        goals = [
            {
                'name': 'New Laptop',
                'target_amount': 1500.00,
                'current_amount': 750.00,
                'target_date': datetime.now() + timedelta(days=90)
            },
            {
                'name': 'Vacation Fund',
                'target_amount': 3000.00,
                'current_amount': 1200.00,
                'target_date': datetime.now() + timedelta(days=180)
            },
            {
                'name': 'Emergency Fund',
                'target_amount': 5000.00,
                'current_amount': 2500.00,
                'target_date': datetime.now() + timedelta(days=365)
            }
        ]

        for goal_data in goals:
            goal = Goal(
                name=goal_data['name'],
                target_amount=goal_data['target_amount'],
                current_amount=goal_data['current_amount'],
                target_date=goal_data['target_date'],
                user_id=test_user.id
            )
            db.session.add(goal)

        # Create sample budgets for current month
        current_month = datetime.now().replace(day=1)
        for category in expense_categories:
            budget = Budget(
                category=category,
                limit=round(random.uniform(200, 1000), 2),
                spent=0.0,
                month=current_month,
                user_id=test_user.id
            )
            db.session.add(budget)

        db.session.commit()
        print("Test data created successfully!")
    except Exception as e:
        print(f"Error creating test data: {e}")
        db.session.rollback()

@app.route('/add_debt', methods=['POST'])
@login_required
def add_debt():
    try:
        data = request.get_json()
        
        # Create new debt
        new_debt = Debt(
            user_id=session['user_id'],
            name=data['name'],
            type=data['type'],
            balance=float(data['balance']),
            original_amount=float(data['balance']),  # Initial balance is the original amount
            interest_rate=float(data['interest_rate']),
            minimum_payment=float(data['minimum_payment']),
            next_payment_date=datetime.strptime(data['next_payment_date'], '%Y-%m-%d'),
            paid_amount=0.0
        )
        
        db.session.add(new_debt)
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Debt added successfully'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 400

@app.route('/update_debt/<int:debt_id>', methods=['POST'])
@login_required
def update_debt(debt_id):
    try:
        debt = Debt.query.filter_by(id=debt_id, user_id=session['user_id']).first_or_404()
        data = request.get_json()
        
        # Update debt fields
        if 'payment_amount' in data:
            payment = float(data['payment_amount'])
            debt.paid_amount += payment
            debt.balance -= payment
            
            # Update next payment date if it's a recurring payment
            if debt.type in ['credit_card', 'loan', 'mortgage']:
                debt.next_payment_date = debt.next_payment_date + timedelta(days=30)
        
        db.session.commit()
        return jsonify({'success': True, 'message': 'Debt updated successfully'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 400

@app.route('/delete_debt/<int:debt_id>', methods=['POST'])
@login_required
def delete_debt(debt_id):
    try:
        debt = Debt.query.filter_by(id=debt_id, user_id=session['user_id']).first_or_404()
        db.session.delete(debt)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Debt deleted successfully'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 400

if __name__ == '__main__':
    with app.app_context():
        
        # Create tables if they don't exist
        db.create_all()
        
        # Only create test user if no users exist
        if User.query.count() == 0:
            create_test_user()
            create_test_data()
            print("Test user and data created successfully! Username: test, Password: test123")
    
    app.run(debug=True)
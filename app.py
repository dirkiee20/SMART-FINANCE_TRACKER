from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
from functools import wraps
import json
import os
import random

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_secret_key'
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'mysql+pymysql://root:@localhost/finance_tracker')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

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

    return render_template('dashboard.html',
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
                         budgets=budgets)

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
    
    # Calculate monthly totals
    monthly_data = {}
    for transaction in transactions:
        month_key = transaction.date.strftime('%Y-%m')
        if month_key not in monthly_data:
            monthly_data[month_key] = {'income': 0.0, 'expense': 0.0}
        monthly_data[month_key][transaction.type] += float(transaction.amount)
    
    # Sort monthly data by date
    monthly_data = dict(sorted(monthly_data.items()))
    
    # Prepare data for charts
    monthly_labels = list(monthly_data.keys())
    monthly_income_data = [float(data['income']) for data in monthly_data.values()]
    monthly_expense_data = [float(data['expense']) for data in monthly_data.values()]
    
    # Calculate current month's totals
    current_month = datetime.now().strftime('%Y-%m')
    monthly_income = float(monthly_data.get(current_month, {}).get('income', 0.0))
    monthly_expenses = float(monthly_data.get(current_month, {}).get('expense', 0.0))
    monthly_savings = monthly_income - monthly_expenses
    
    # Calculate category breakdown for current month
    category_breakdown = []
    category_totals = {}
    
    for transaction in transactions:
        if transaction.date.strftime('%Y-%m') == current_month and transaction.type == 'expense':
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
    
    return render_template('reports.html',
                         monthly_labels=monthly_labels,
                         monthly_income_data=monthly_income_data,
                         monthly_expense_data=monthly_expense_data,
                         monthly_income=monthly_income,
                         monthly_expenses=monthly_expenses,
                         monthly_savings=monthly_savings,
                         category_breakdown=category_breakdown,
                         category_labels=category_labels,
                         category_data=category_data)

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
    query = request.json.get('query')
    # Here you would integrate with an AI service
    # For now, return some sample responses
    responses = {
        'spending': 'Based on your spending patterns, you could save more in the dining category.',
        'budget': 'Your current budget utilization is at 75%. You\'re doing well!',
        'savings': 'You\'re on track to meet your savings goal by December.',
    }
    
    return jsonify({
        'response': responses.get(query.lower(), 
            "I can help you analyze your spending, budget, and savings. What would you like to know?")
    })

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
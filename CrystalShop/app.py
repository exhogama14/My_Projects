from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
from functools import wraps
import os
import re

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'crystal-supply-secret-2026')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///site.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'static/images'
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)
app.config['SESSION_REFRESH_EACH_REQUEST'] = True

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to continue.'
login_manager.login_message_category = 'info'

# ============ DATABASE MODELS ============
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False, index=True)
    email = db.Column(db.String(100), unique=True, nullable=False, index=True)
    password = db.Column(db.String(200), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f'<User {self.username}>'

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, index=True)
    description = db.Column(db.String(500), nullable=True)
    price = db.Column(db.Float, nullable=False)
    image = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<Product {self.name}>'

class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_name = db.Column(db.String(100), nullable=False)
    customer_email = db.Column(db.String(100), nullable=False, index=True)
    total = db.Column(db.Float, nullable=False)
    
    shipping_address = db.Column(db.String(200), nullable=True)
    city = db.Column(db.String(100), nullable=True)
    state = db.Column(db.String(100), nullable=True)
    zip_code = db.Column(db.String(20), nullable=True)
    country = db.Column(db.String(50), nullable=True)

    billing_address = db.Column(db.String(200), nullable=True)
    billing_city = db.Column(db.String(100), nullable=True)
    billing_state = db.Column(db.String(100), nullable=True)
    billing_zip_code = db.Column(db.String(20), nullable=True)
    billing_country = db.Column(db.String(50), nullable=True)
    same_as_shipping = db.Column(db.Boolean, default=True)

    card_holder = db.Column(db.String(100), nullable=True)
    card_number = db.Column(db.String(20), nullable=True)
    card_expiry = db.Column(db.String(5), nullable=True)
    card_cvv = db.Column(db.String(4), nullable=True)
    card_type = db.Column(db.String(20), nullable=True)
    
    is_guest = db.Column(db.Boolean, default=False)
    date_ordered = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    
    def __repr__(self):
        return f'<Order {self.id}>'

# ============ AUTH HELPERS ============
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('Admin access required.', 'error')
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated_function

def validate_email(email):
    return re.match(r'^[\w\.-]+@[\w\.-]+\.\w+$', email) is not None

def validate_username(username):
    return len(username) >= 3 and len(username) <= 50 and re.match(r'^[a-zA-Z0-9_-]+$', username) is not None

# ============ CART HELPERS ============
def get_cart():
    return session.get('cart', [])

def add_to_cart(product_id):
    try:
        product_id = int(product_id)
        product = Product.query.get(product_id)
        if not product:
            return False
        cart = get_cart()
        for item in cart:
            if item['id'] == product_id:
                item['quantity'] += 1
                session['cart'] = cart
                session.modified = True
                return True
        cart.append({'id': product_id, 'quantity': 1})
        session['cart'] = cart
        session.modified = True
        return True
    except:
        return False

def remove_from_cart(product_id):
    try:
        product_id = int(product_id)
        session['cart'] = [item for item in get_cart() if item['id'] != product_id]
        session.modified = True
        return True
    except:
        return False

def get_cart_total():
    total = 0
    for item in get_cart():
        product = Product.query.get(item['id'])
        if product:
            total += product.price * item['quantity']
    return round(total, 2)

# ============ DATABASE INIT ============
def init_db():
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(username='exhog').first():
            admin = User(username='exhog', email='admin@crystalsupply.com', password=generate_password_hash('root'), is_admin=True)
            db.session.add(admin)
            db.session.commit()
            print("[OK] Admin user 'exhog' created (pass: root)")

# ============ PUBLIC ROUTES ============
@app.route('/')
def home():
    page = max(1, request.args.get('page', default=1, type=int))
    per_page = 20
    total = Product.query.count()
    total_pages = max(1, (total + per_page - 1) // per_page) if total else 1
    if page > total_pages:
        page = total_pages
    products = Product.query.order_by(Product.id.asc()).offset((page - 1) * per_page).limit(per_page).all()
    return render_template('home.html', products=products, page=page, total_pages=total_pages, total=total)

@app.route('/product/<int:id>')
def product_detail(id):
    product = Product.query.get_or_404(id)
    return render_template('product.html', product=product)

@app.route('/cart')
def cart():
    cart_items = []
    total = 0
    for item in get_cart():
        product = Product.query.get(item['id'])
        if product:
            cart_items.append({'product': product, 'quantity': item['quantity']})
            total += product.price * item['quantity']
    return render_template('cart.html', cart_items=cart_items, total=round(total, 2))

@app.route('/cart/add/<int:id>', methods=['POST'])
def cart_add(id):
    if add_to_cart(id):
        flash('Item added to cart!', 'success')
    else:
        flash('Could not add item to cart.', 'error')
    return redirect(request.referrer or url_for('home'))

@app.route('/cart/remove/<int:id>', methods=['POST'])
def cart_remove(id):
    if remove_from_cart(id):
        flash('Item removed from cart.', 'info')
    else:
        flash('Could not remove item.', 'error')
    return redirect(url_for('cart'))

@app.route('/checkout', methods=['GET', 'POST'])
def checkout():
    if request.method == 'POST':
        cart = get_cart()
        if not cart:
            flash('Cart is empty!', 'warning')
            return redirect(url_for('cart'))
        
        total = get_cart_total()
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()
        is_guest = request.form.get('is_guest') == 'true'
        
        if not name or not email:
            flash('Name and email are required.', 'error')
            return redirect(url_for('checkout'))
        
        shipping_address = request.form.get('shipping_address')
        city = request.form.get('city')
        state = request.form.get('state')
        zip_code = request.form.get('zip_code')
        country = request.form.get('country')

        same_as_shipping = request.form.get('same_as_shipping') == 'on'
        if same_as_shipping:
            billing_address = shipping_address
            billing_city = city
            billing_state = state
            billing_zip_code = zip_code
            billing_country = country
        else:
            billing_address = request.form.get('billing_address')
            billing_city = request.form.get('billing_city')
            billing_state = request.form.get('billing_state')
            billing_zip_code = request.form.get('billing_zip_code')
            billing_country = request.form.get('billing_country')
        
        card_holder = request.form.get('card_holder')
        card_number = request.form.get('card_number')
        card_expiry = request.form.get('card_expiry')
        card_cvv = request.form.get('card_cvv')
        card_type = request.form.get('card_type')

        new_order = Order(
            customer_name=name, customer_email=email, total=total,
            shipping_address=shipping_address, city=city, state=state, zip_code=zip_code, country=country,
            billing_address=billing_address, billing_city=billing_city, billing_state=billing_state,
            billing_zip_code=billing_zip_code, billing_country=billing_country, same_as_shipping=same_as_shipping,
            card_holder=card_holder, card_number=card_number,
            card_expiry=card_expiry, card_cvv=card_cvv,
            card_type=card_type, is_guest=is_guest
        )
        db.session.add(new_order)
        db.session.commit()
        session['cart'] = []
        session.modified = True
        flash('Order placed! Check admin panel.', 'success')
        return redirect(url_for('home'))
    
    cart_items = []
    total = 0
    for item in get_cart():
        product = Product.query.get(item['id'])
        if product:
            cart_items.append({'product': product, 'quantity': item['quantity']})
            total += product.price * item['quantity']
    return render_template('checkout.html', cart_items=cart_items, total=round(total, 2))

@app.route('/contact')
def contact():
    return render_template('contact.html')

# ============ AUTH ROUTES ============
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        
        if not username or not password:
            flash('Username and password required.', 'error')
            return redirect(url_for('login'))
        
        user = User.query.filter_by(username=username).first() or User.query.filter_by(email=username).first()
        if user and check_password_hash(user.password, password):
            login_user(user, remember=True)
            flash(f'Welcome back, {user.username}!', 'success')
            return redirect(request.args.get('next') or url_for('home'))
        else:
            flash('Invalid username or password.', 'error')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        
        if not validate_username(username):
            flash('Username must be 3-50 characters, alphanumeric with hyphens/underscores.', 'error')
            return redirect(url_for('register'))
        
        if not validate_email(email):
            flash('Please enter a valid email address.', 'error')
            return redirect(url_for('register'))
        
        if len(password) < 6:
            flash('Password must be at least 6 characters.', 'error')
            return redirect(url_for('register'))
        
        if User.query.filter_by(username=username).first():
            flash('Username already exists.', 'error')
            return redirect(url_for('register'))
        
        if User.query.filter_by(email=email).first():
            flash('Email already registered.', 'error')
            return redirect(url_for('register'))
        
        new_user = User(username=username, email=email, password=generate_password_hash(password))
        db.session.add(new_user)
        db.session.commit()
        flash('Account created! Please log in.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('home'))

# ============ ADMIN ROUTES ============
@app.route('/admin')
@login_required
@admin_required
def admin():
    products = Product.query.all()
    orders = Order.query.order_by(Order.date_ordered.desc()).all()
    return render_template('admin.html', products=products, orders=orders)

@app.route('/admin/product/add', methods=['POST'])
@login_required
@admin_required
def admin_add_product():
    name = request.form.get('name')
    description = request.form.get('description')
    price = request.form.get('price')
    image_file = request.files.get('image')
    image_name = None
    if image_file and image_file.filename:
        image_name = secure_filename(image_file.filename)
        image_file.save(os.path.join(app.config['UPLOAD_FOLDER'], image_name))
    new_product = Product(name=name, description=description, price=price, image=image_name)
    db.session.add(new_product)
    db.session.commit()
    flash('Product added!', 'success')
    return redirect(url_for('admin'))

@app.route('/admin/product/delete/<int:id>', methods=['POST'])
@login_required
@admin_required
def admin_delete_product(id):
    product = Product.query.get_or_404(id)
    db.session.delete(product)
    db.session.commit()
    flash('Product deleted.', 'info')
    return redirect(url_for('admin'))

# ============ ERROR HANDLERS ============
@app.errorhandler(404)
def not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(500)
def server_error(e):
    db.session.rollback()
    return render_template('500.html'), 500

# ============ APP INITIALIZATION ============
if __name__ == '__main__':
    init_db()
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    print("[OK] Crystal Supply server starting...")
    print("[OK] Database ready")
    print("[OK] Running on http://0.0.0.0:8000")
    app.run(debug=False, port=8000, host='0.0.0.0')

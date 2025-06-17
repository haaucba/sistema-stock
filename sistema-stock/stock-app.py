from flask import Flask, request, jsonify, render_template
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from flask_jwt_extended import JWTManager, jwt_required, create_access_token, get_jwt_identity
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = 'tu-clave-secreta-aqui'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///stock_system.db'
app.config['JWT_SECRET_KEY'] = 'jwt-secret-string'
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(hours=24)

db = SQLAlchemy(app)
jwt = JWTManager(app)
CORS(app)

# Modelos de Base de Datos
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # 'admin' o 'user'
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class ProductMaster(db.Model):
    product_id = db.Column(db.Integer, primary_key=True)
    product_name = db.Column(db.String(100), nullable=False)
    sku = db.Column(db.String(50), unique=True, nullable=False)
    unit_of_measure = db.Column(db.String(20), nullable=False)
    cost = db.Column(db.Float, nullable=False)
    sale_price = db.Column(db.Float, nullable=False)
    category = db.Column(db.String(50), nullable=False)
    location = db.Column(db.String(50), nullable=False)
    active = db.Column(db.Boolean, default=True)

class InventoryMovement(db.Model):
    movement_id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    product_id = db.Column(db.Integer, db.ForeignKey('product_master.product_id'), nullable=False)
    movement_type = db.Column(db.String(20), nullable=False)  # 'entrada', 'salida', 'ajuste'
    quantity = db.Column(db.Integer, nullable=False)
    order_id = db.Column(db.String(50))
    notes = db.Column(db.Text)

class CurrentStock(db.Model):
    product_id = db.Column(db.Integer, db.ForeignKey('product_master.product_id'), primary_key=True)
    quantity = db.Column(db.Integer, nullable=False, default=0)
    last_updated = db.Column(db.DateTime, default=datetime.utcnow)
    total_inventory_cost = db.Column(db.Float, nullable=False, default=0)

class PredictorStock(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product_master.product_id'), nullable=False)
    units_sold = db.Column(db.Integer, nullable=False)
    avg_sale_price = db.Column(db.Float, nullable=False)
    promotion_active = db.Column(db.Boolean, default=False)
    special_event = db.Column(db.String(100))

# Rutas de Autenticación
@app.route('/api/register', methods=['POST'])
def register():
    data = request.get_json()
    
    if User.query.filter_by(username=data['username']).first():
        return jsonify({'message': 'Usuario ya existe'}), 400
    
    user = User(
        username=data['username'],
        role=data.get('role', 'user')
    )
    user.set_password(data['password'])
    
    db.session.add(user)
    db.session.commit()
    
    return jsonify({'message': 'Usuario creado exitosamente'}), 201

@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()
    user = User.query.filter_by(username=data['username']).first()
    
    if user and user.check_password(data['password']):
        access_token = create_access_token(
            identity=user.username,
            additional_claims={'role': user.role}
        )
        return jsonify({
            'access_token': access_token,
            'role': user.role,
            'username': user.username
        })
    
    return jsonify({'message': 'Credenciales inválidas'}), 401

# Rutas de Productos
@app.route('/api/products', methods=['GET'])
@jwt_required()
def get_products():
    products = ProductMaster.query.all()
    return jsonify([{
        'product_id': p.product_id,
        'product_name': p.product_name,
        'sku': p.sku,
        'unit_of_measure': p.unit_of_measure,
        'cost': p.cost,
        'sale_price': p.sale_price,
        'category': p.category,
        'location': p.location,
        'active': p.active
    } for p in products])

@app.route('/api/products', methods=['POST'])
@jwt_required()
def create_product():
    data = request.get_json()
    product = ProductMaster(
        product_name=data['product_name'],
        sku=data['sku'],
        unit_of_measure=data['unit_of_measure'],
        cost=data['cost'],
        sale_price=data['sale_price'],
        category=data['category'],
        location=data['location'],
        active=data.get('active', True)
    )
    
    db.session.add(product)
    db.session.commit()
    
    # Crear registro de stock inicial
    stock = CurrentStock(
        product_id=product.product_id,
        quantity=0,
        total_inventory_cost=0
    )
    db.session.add(stock)
    db.session.commit()
    
    return jsonify({'message': 'Producto creado exitosamente', 'product_id': product.product_id}), 201

@app.route('/api/products/<int:product_id>', methods=['PUT'])
@jwt_required()
def update_product(product_id):
    product = ProductMaster.query.get_or_404(product_id)
    data = request.get_json()
    
    product.product_name = data.get('product_name', product.product_name)
    product.sku = data.get('sku', product.sku)
    product.unit_of_measure = data.get('unit_of_measure', product.unit_of_measure)
    product.cost = data.get('cost', product.cost)
    product.sale_price = data.get('sale_price', product.sale_price)
    product.category = data.get('category', product.category)
    product.location = data.get('location', product.location)
    product.active = data.get('active', product.active)
    
    db.session.commit()
    return jsonify({'message': 'Producto actualizado exitosamente'})

@app.route('/api/products/<int:product_id>', methods=['DELETE'])
@jwt_required()
def delete_product(product_id):
    product = ProductMaster.query.get_or_404(product_id)
    # Primero, borrar cualquier stock y movimientos asociados (opcional):
    CurrentStock.query.filter_by(product_id=product_id).delete()
    InventoryMovement.query.filter_by(product_id=product_id).delete()
    # Ahora, borrar el propio producto
    db.session.delete(product)
    db.session.commit()
    return jsonify({'message': 'Producto eliminado exitosamente'})

# Rutas de Movimientos de Inventario
#*@app.route('/api/movements', methods=['GET'])
#@jwt_required()
#def get_movements():
#    movements = InventoryMovement.query.order_by(InventoryMovement.date.desc()).all()
#    return jsonify([{
#        'movement_id': m.movement_id,
#        'date': m.date.isoformat(),
#        'product_id': m.product_id,
#        'movement_type': m.movement_type,
#        'quantity': m.quantity,
#        'order_id': m.order_id,
#        'notes': m.notes
#    } for m in movements])
# 
@app.route('/api/movements', methods=['GET'])
@jwt_required()
def get_movements():
    # Hacemos un join con ProductMaster para traer también el nombre del producto
    mov_query = db.session.query(
        InventoryMovement,
        ProductMaster
    ).join(ProductMaster, InventoryMovement.product_id == ProductMaster.product_id) \
     .order_by(InventoryMovement.date.desc()).all()

    return jsonify([{
        'movement_id'  : m.movement_id,
        'date'         : m.date.isoformat(),
        'product_id'   : m.product_id,
        'product_name' : p.product_name,       # <-- Nombre del producto
        'movement_type': m.movement_type,
        'quantity'     : m.quantity,
        'order_id'     : m.order_id,
        'notes'        : m.notes
    } for m, p in mov_query])   

@app.route('/api/movements', methods=['POST'])
@jwt_required()
def create_movement():
    data = request.get_json()
    
    movement = InventoryMovement(
        product_id=data['product_id'],
        movement_type=data['movement_type'],
        quantity=data['quantity'],
        order_id=data.get('order_id'),
        notes=data.get('notes')
    )

   
    db.session.add(movement)

    
    # Actualizar stock actual
    stock = CurrentStock.query.filter_by(product_id=data['product_id']).first()
    if not stock:
        stock = CurrentStock(product_id=data['product_id'], quantity=0, total_inventory_cost=0)
        db.session.add(stock)
    
    if data['movement_type'] == 'entrada':
        stock.quantity += data['quantity']
    elif data['movement_type'] == 'salida':
        stock.quantity -= data['quantity']
    elif data['movement_type'] == 'ajuste':
        stock.quantity = data['quantity']
    
    # Actualizar costo total de inventario
    product = ProductMaster.query.get(data['product_id'])
    stock.total_inventory_cost = stock.quantity * product.cost
    stock.last_updated = datetime.utcnow()
    
    db.session.commit()
    return jsonify({'message': 'Movimiento registrado exitosamente'}), 201

# Rutas de Stock Actual
@app.route('/api/stock', methods=['GET'])
@jwt_required()
def get_current_stock():
    stock_query = db.session.query(
        CurrentStock,
        ProductMaster
    ).join(ProductMaster).all()
    
    return jsonify([{
        'product_id': stock.CurrentStock.product_id,
        'product_name': stock.ProductMaster.product_name,
        'sku': stock.ProductMaster.sku,
        'quantity': stock.CurrentStock.quantity,
        'cost': stock.ProductMaster.cost,
        'total_inventory_cost': stock.CurrentStock.total_inventory_cost,
        'last_updated': stock.CurrentStock.last_updated.isoformat()
    } for stock in stock_query])

# Rutas de Predicción
@app.route('/api/predictions', methods=['GET'])
@jwt_required()
def get_predictions():
    try:
        predictions = []
        products = ProductMaster.query.filter_by(active=True).all()
        
        for product in products:
            # Obtener datos históricos
            historical_data = PredictorStock.query.filter_by(
                product_id=product.product_id
            ).order_by(PredictorStock.date).all()
            
            if len(historical_data) < 5:  # Necesitamos al menos 5 puntos de datos
                predictions.append({
                    'product_id': product.product_id,
                    'product_name': product.product_name,
                    'prediction': 'Datos insuficientes',
                    'confidence': 0,
                    'trend': 'unknown'
                })
                continue
            
            # Preparar datos para predicción
            dates = [(h.date - historical_data[0].date).days for h in historical_data]
            sales = [h.units_sold for h in historical_data]
            
            # Crear modelo de regresión lineal
            X = np.array(dates).reshape(-1, 1)
            y = np.array(sales)
            
            model = LinearRegression()
            model.fit(X, y)
            
            # Predecir próximos 30 días
            future_date = (datetime.now().date() - historical_data[0].date).days + 30
            prediction = model.predict([[future_date]])[0]
            
            # Calcular tendencia
            trend = 'creciente' if model.coef_[0] > 0 else 'decreciente'
            
            # Calcular confianza (basado en R²)
            confidence = max(0, min(100, model.score(X, y) * 100))
            
            predictions.append({
                'product_id': product.product_id,
                'product_name': product.product_name,
                'prediction': max(0, int(prediction)),
                'confidence': round(confidence, 2),
                'trend': trend
            })
        
        return jsonify(predictions)
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/predictor-data', methods=['POST'])
@jwt_required()
def add_predictor_data():
    data = request.get_json()
    
    predictor_data = PredictorStock(
        date=datetime.strptime(data['date'], '%Y-%m-%d').date(),
        product_id=data['product_id'],
        units_sold=data['units_sold'],
        avg_sale_price=data['avg_sale_price'],
        promotion_active=data.get('promotion_active', False),
        special_event=data.get('special_event')
    )
    
    db.session.add(predictor_data)
    db.session.commit()
    
    return jsonify({'message': 'Datos de predicción agregados exitosamente'}), 201

# Ruta principal para servir la aplicación web
@app.route('/')
def index():
    return render_template('index.html')

# Inicialización de la base de datos
def init_database():
    with app.app_context():
        db.create_all()
        
        # Crear usuarios por defecto si no existen
        if not User.query.first():
            admin = User(username='admin', role='admin')
            admin.set_password('admin123')
            
            user = User(username='user', role='user')
            user.set_password('user123')
            
            db.session.add(admin)
            db.session.add(user)
            db.session.commit()
            
            print("Usuarios creados:")
            print("Admin: admin / admin123")
            print("User: user / user123")


# Funciona con http
#if __name__ == '__main__':
#    init_database()
#    app.run(debug=True, host='0.0.0.0', port=5000)


# Funciona con https 
if __name__ == '__main__':
    init_database()
    app.run(
        host='0.0.0.0',
        port=5000,
        debug=True,
        ssl_context='adhoc'
    )


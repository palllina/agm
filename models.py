"""
Модели базы данных для системы авторизации и сохранения результатов
"""
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta, timezone

# Московский часовой пояс (UTC+3)
MOSCOW_TZ = timezone(timedelta(hours=3))

def moscow_now():
    """Возвращает текущее время в московском часовом поясе"""
    return datetime.now(MOSCOW_TZ)

db = SQLAlchemy()


class User(UserMixin, db.Model):
    """Модель пользователя"""
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=moscow_now)
    
    # Связь с сохраненными результатами
    saved_results = db.relationship('SavedResult', backref='user', lazy=True, cascade='all, delete-orphan')
    
    def set_password(self, password):
        """Установить пароль (хеширование)"""
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        """Проверить пароль"""
        return check_password_hash(self.password_hash, password)
    
    def to_dict(self):
        """Преобразовать в словарь"""
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'is_admin': self.is_admin,
            'created_at': self.created_at.isoformat(),
            'saved_count': len(self.saved_results)
        }


class SavedResult(db.Model):
    """Модель сохраненного результата подбора насоса"""
    __tablename__ = 'saved_results'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    
    # Параметры подбора
    flow = db.Column(db.Float, nullable=False)
    head = db.Column(db.Float, nullable=False)
    static_head = db.Column(db.Float)
    density = db.Column(db.Float)
    pump_type = db.Column(db.String(50))
    
    # Выбранный насос
    selected_pump = db.Column(db.String(200))
    
    # Полные данные в JSON формате (все параметры подбора)
    data = db.Column(db.Text, nullable=False)
    
    # Метаданные
    created_at = db.Column(db.DateTime, default=moscow_now)
    updated_at = db.Column(db.DateTime, default=moscow_now, onupdate=moscow_now)
    
    def to_dict(self):
        """Преобразовать в словарь"""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'title': self.title,
            'flow': self.flow,
            'head': self.head,
            'static_head': self.static_head,
            'density': self.density,
            'pump_type': self.pump_type,
            'selected_pump': self.selected_pump,
            'data': self.data,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }


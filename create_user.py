#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Скрипт для создания пользователей (только для администратора)
"""
from app import app
from models import db, User
import sys

def create_user(username, password, email=None, is_admin=False):
    """Создать нового пользователя"""
    with app.app_context():
        # Проверка существования пользователя
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            print(f"❌ Пользователь '{username}' уже существует!")
            return False
        
        # Создание email если не указан
        if not email:
            email = f"{username}@agm.local"
        
        # Создание нового пользователя
        user = User(username=username, email=email, is_admin=is_admin)
        user.set_password(password)
        
        db.session.add(user)
        db.session.commit()
        
        admin_text = " (АДМИНИСТРАТОР)" if is_admin else ""
        print(f"✅ Пользователь '{username}' успешно создан!{admin_text}")
        print(f"   Email: {email}")
        if is_admin:
            print(f"   👑 Права: Администратор (видит все результаты)")
        return True

def list_users():
    """Показать всех пользователей"""
    with app.app_context():
        users = User.query.all()
        if not users:
            print("📭 Пользователей нет в базе данных")
            return
        
        print("\n" + "="*60)
        print("👥 СПИСОК ПОЛЬЗОВАТЕЛЕЙ")
        print("="*60)
        for user in users:
            admin_badge = " 👑 АДМИНИСТРАТОР" if user.is_admin else ""
            print(f"  ID: {user.id}")
            print(f"  Имя: {user.username}{admin_badge}")
            print(f"  Email: {user.email}")
            print(f"  Создан: {user.created_at.strftime('%d.%m.%Y %H:%M')}")
            print(f"  Результатов: {len(user.saved_results)}")
            print("-"*60)

def delete_user(username):
    """Удалить пользователя"""
    with app.app_context():
        user = User.query.filter_by(username=username).first()
        if not user:
            print(f"❌ Пользователь '{username}' не найден!")
            return False
        
        # Подтверждение
        confirm = input(f"⚠️  Удалить пользователя '{username}' и все его результаты? (yes/no): ")
        if confirm.lower() != 'yes':
            print("❌ Отменено")
            return False
        
        db.session.delete(user)
        db.session.commit()
        
        print(f"✅ Пользователь '{username}' удален!")
        return True

def change_password(username, new_password):
    """Изменить пароль пользователя"""
    with app.app_context():
        user = User.query.filter_by(username=username).first()
        if not user:
            print(f"❌ Пользователь '{username}' не найден!")
            return False
        
        user.set_password(new_password)
        db.session.commit()
        
        print(f"✅ Пароль пользователя '{username}' изменен!")
        return True

def toggle_admin(username):
    """Переключить права администратора"""
    with app.app_context():
        user = User.query.filter_by(username=username).first()
        if not user:
            print(f"❌ Пользователь '{username}' не найден!")
            return False
        
        user.is_admin = not user.is_admin
        db.session.commit()
        
        status = "АДМИНИСТРАТОРОМ" if user.is_admin else "обычным пользователем"
        print(f"✅ Пользователь '{username}' теперь {status}!")
        return True

def interactive_mode():
    """Интерактивный режим"""
    print("\n" + "="*60)
    print("🔐 AGM - УПРАВЛЕНИЕ ПОЛЬЗОВАТЕЛЯМИ")
    print("="*60)
    print("\nВыберите действие:")
    print("  1 - Создать пользователя")
    print("  2 - Показать всех пользователей")
    print("  3 - Удалить пользователя")
    print("  4 - Изменить пароль")
    print("  5 - Переключить права администратора")
    print("  0 - Выход")
    print()
    
    choice = input("Ваш выбор: ").strip()
    
    if choice == "1":
        username = input("Имя пользователя: ").strip()
        password = input("Пароль: ").strip()
        email = input("Email (Enter для автоматического): ").strip()
        is_admin_input = input("Администратор? (y/n): ").strip().lower()
        
        if not username or not password:
            print("❌ Имя пользователя и пароль обязательны!")
            return
        
        is_admin = is_admin_input == 'y'
        create_user(username, password, email if email else None, is_admin)
    
    elif choice == "2":
        list_users()
    
    elif choice == "3":
        username = input("Имя пользователя для удаления: ").strip()
        if username:
            delete_user(username)
    
    elif choice == "4":
        username = input("Имя пользователя: ").strip()
        new_password = input("Новый пароль: ").strip()
        if username and new_password:
            change_password(username, new_password)
    
    elif choice == "5":
        username = input("Имя пользователя: ").strip()
        if username:
            toggle_admin(username)
    
    elif choice == "0":
        print("👋 До свидания!")
        return
    
    else:
        print("❌ Неверный выбор!")

if __name__ == '__main__':
    # Проверка аргументов командной строки
    if len(sys.argv) > 1:
        command = sys.argv[1]
        
        if command == "create" and len(sys.argv) >= 4:
            # python create_user.py create username password [email] [--admin]
            username = sys.argv[2]
            password = sys.argv[3]
            email = None
            is_admin = False
            
            # Проверяем дополнительные аргументы
            for i in range(4, len(sys.argv)):
                if sys.argv[i] == '--admin':
                    is_admin = True
                elif '@' in sys.argv[i]:
                    email = sys.argv[i]
            
            create_user(username, password, email, is_admin)
        
        elif command == "list":
            # python create_user.py list
            list_users()
        
        elif command == "delete" and len(sys.argv) >= 3:
            # python create_user.py delete username
            username = sys.argv[2]
            delete_user(username)
        
        elif command == "password" and len(sys.argv) >= 4:
            # python create_user.py password username new_password
            username = sys.argv[2]
            new_password = sys.argv[3]
            change_password(username, new_password)
        
        elif command == "admin" and len(sys.argv) >= 3:
            # python create_user.py admin username
            username = sys.argv[2]
            toggle_admin(username)
        
        else:
            print("❌ Неверные аргументы!")
            print("\nИспользование:")
            print("  python create_user.py create <username> <password> [email] [--admin]")
            print("  python create_user.py list")
            print("  python create_user.py delete <username>")
            print("  python create_user.py password <username> <new_password>")
            print("  python create_user.py admin <username>  # переключить права админа")
            print("\nИли запустите без аргументов для интерактивного режима")
    
    else:
        # Интерактивный режим
        interactive_mode()


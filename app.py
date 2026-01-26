"""
AGM - Backend для подбора насосного оборудования
Flask сервер с API endpoints
"""

from flask import Flask, render_template, jsonify, request, send_from_directory, session, redirect, url_for, send_file
from flask_cors import CORS
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
import json
import os
from datetime import datetime, timedelta
import requests
from dotenv import load_dotenv
from models import db, User, SavedResult
import tempfile
import subprocess
from io import BytesIO

# Загрузка переменных окружения
load_dotenv()

app = Flask(__name__, 
            static_folder='.',
            template_folder='.')

# Конфигурация
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'

# База данных: PostgreSQL для production, SQLite для разработки
database_url = os.environ.get('DATABASE_URL')
if database_url:
    # Для облачных платформ (Render, Railway, Heroku) - PostgreSQL
    # DATABASE_URL обычно в формате: postgresql://user:pass@host:port/dbname
    # Некоторые платформы используют postgres://, нужно заменить на postgresql://
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
else:
    # Для локальной разработки - SQLite
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///agm.db'

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)

# Инициализация расширений
db.init_app(app)
CORS(app, supports_credentials=True)

# Настройка Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login_page'

@login_manager.user_loader
def load_user(user_id):
    """Загрузка пользователя для Flask-Login"""
    return User.query.get(int(user_id))

# Создание таблиц БД при первом запуске
with app.app_context():
    db.create_all()


# ============= ПОЛУЧЕНИЕ IP-АДРЕСА КЛИЕНТА =============

def get_client_ip():
    """Получение реального IP-адреса клиента"""
    # Проверяем заголовки прокси (в порядке приоритета)
    # X-Forwarded-For может содержать несколько IP через запятую
    x_forwarded_for = request.headers.get('X-Forwarded-For')
    if x_forwarded_for:
        # Берем первый IP из списка (реальный IP клиента)
        ip = x_forwarded_for.split(',')[0].strip()
        if ip and ip != 'unknown':
            return ip
    
    # Проверяем X-Real-IP
    x_real_ip = request.headers.get('X-Real-IP')
    if x_real_ip:
        ip = x_real_ip.strip()
        if ip and ip != 'unknown':
            return ip
    
    # Проверяем CF-Connecting-IP (Cloudflare)
    cf_ip = request.headers.get('CF-Connecting-IP')
    if cf_ip:
        ip = cf_ip.strip()
        if ip and ip != 'unknown':
            return ip
    
    # Если нет прокси, используем remote_addr
    remote_addr = request.remote_addr
    if remote_addr and remote_addr != 'unknown':
        return remote_addr
    
    # Последний вариант - пробуем получить из environ
    if request.environ.get('HTTP_X_FORWARDED_FOR'):
        ip = request.environ.get('HTTP_X_FORWARDED_FOR').split(',')[0].strip()
        if ip and ip != 'unknown':
            return ip
    
    return 'Unknown'

# Загрузка данных о насосах из JSON файла
def load_pump_data():
    """Загружает данные о насосах из data.json"""
    try:
        with open('data.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print("⚠️  Файл data.json не найден!")
        return None
    except json.JSONDecodeError as e:
        print(f"⚠️  Ошибка парсинга JSON: {e}")
        return None

# Кэшируем данные при старте
PUMP_DATA = load_pump_data()


# ============= МАРШРУТЫ ДЛЯ HTML СТРАНИЦ =============

@app.route('/')
def index():
    """Главная страница - подбор насоса"""
    return send_from_directory('.', 'select.html')

@app.route('/select.html')
def select_page():
    """Страница подбора насоса"""
    return send_from_directory('.', 'select.html')

@app.route('/calc.html')
def calc_page():
    """Страница расчёта трубопровода"""
    return send_from_directory('.', 'calc.html')

@app.route('/result.html')
def result_page():
    """Страница результатов"""
    return send_from_directory('.', 'result.html')

@app.route('/login.html')
def login_page():
    """Страница входа/регистрации"""
    return send_from_directory('.', 'login.html')

@app.route('/saved.html')
@login_required
def saved_page():
    """Страница сохраненных результатов (требует авторизации)"""
    return send_from_directory('.', 'saved.html')


# ============= API ENDPOINTS =============

@app.route('/api/pumps', methods=['GET'])
def get_all_pumps():
    """
    Получить все данные о насосах
    GET /api/pumps
    """
    if PUMP_DATA is None:
        return jsonify({"error": "Данные о насосах не загружены"}), 500
    
    return jsonify(PUMP_DATA), 200


@app.route('/api/pumps/filter', methods=['POST'])
def filter_pumps():
    """
    Фильтрация насосов по параметрам
    POST /api/pumps/filter
    Body: {
        "flow": 100,          # Подача, м³/ч
        "head": 10,           # Напор, м
        "pumpType": "sewage", # Тип насоса
        "density": 1000       # Плотность, кг/м³
    }
    """
    if PUMP_DATA is None:
        return jsonify({"error": "Данные о насосах не загружены"}), 500
    
    data = request.get_json()
    
    # Получаем параметры из запроса
    flow = data.get('flow')
    head = data.get('head')
    pump_type = data.get('pumpType', 'sewage')
    density = data.get('density', 1000)
    
    if flow is None or head is None:
        return jsonify({"error": "Необходимо указать flow и head"}), 400
    
    # Здесь можно добавить логику фильтрации
    # Пока возвращаем все насосы
    filtered_pumps = PUMP_DATA.get('pumpParabolas', [])
    
    return jsonify({
        "pumps": filtered_pumps,
        "filters": {
            "flow": flow,
            "head": head,
            "pumpType": pump_type,
            "density": density
        }
    }), 200


@app.route('/api/pump/<pump_name>', methods=['GET'])
def get_pump_by_name(pump_name):
    """
    Получить информацию о конкретном насосе по имени
    GET /api/pump/N_3069_MT_430
    """
    if PUMP_DATA is None:
        return jsonify({"error": "Данные о насосах не загружены"}), 500
    
    # Заменяем подчеркивания на пробелы
    pump_name = pump_name.replace('_', ' ')
    
    # Ищем насос в массиве
    for pump in PUMP_DATA.get('pumpParabolas', []):
        if pump.get('name') == pump_name:
            # Добавляем дополнительную информацию
            pump_info = pump.copy()
            pump_info['weight'] = PUMP_DATA.get('pumpWeights', {}).get(pump_name)
            pump_info['dimensions'] = PUMP_DATA.get('pumpDimensions', {}).get(pump_name)
            return jsonify(pump_info), 200
    
    return jsonify({"error": f"Насос '{pump_name}' не найден"}), 404


@app.route('/api/calculate', methods=['POST'])
def calculate_pump():
    """
    Расчёт подходящих насосов
    POST /api/calculate
    Body: {
        "flow": 100,
        "head": 10,
        "staticHead": 5,
        "density": 1000,
        "pumpType": "sewage",
        "material": "чугун",
        "voltage": 380,
        "cableLength": 10,
        "insulationClass": "F",
        "explosionProof": "нет"
    }
    """
    if PUMP_DATA is None:
        return jsonify({"error": "Данные о насосах не загружены"}), 500
    
    data = request.get_json()
    
    # Логируем запрос
    print(f"📊 Расчёт насоса: подача={data.get('flow')}, напор={data.get('head')}")
    
    # Здесь можно добавить сложную логику расчёта
    # Пока просто возвращаем параметры
    
    return jsonify({
        "success": True,
        "timestamp": datetime.now().isoformat(),
        "input": data,
        "message": "Расчёт выполнен успешно"
    }), 200


@app.route('/api/motors', methods=['GET'])
def get_motors():
    """
    Получить список доступных двигателей
    GET /api/motors
    """
    if PUMP_DATA is None:
        return jsonify({"error": "Данные не загружены"}), 500
    
    motors = PUMP_DATA.get('motors', [])
    return jsonify({"motors": motors, "count": len(motors)}), 200


@app.route('/api/health', methods=['GET'])
def health_check():
    """
    Проверка работоспособности сервера
    GET /api/health
    """
    return jsonify({
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "data_loaded": PUMP_DATA is not None,
        "pump_count": len(PUMP_DATA.get('pumpParabolas', [])) if PUMP_DATA else 0
    }), 200


@app.route('/api/client-info', methods=['GET'])
def get_client_info():
    """
    Получить информацию о клиенте (IP и настройки отображения)
    GET /api/client-info
    """
    client_ip = get_client_ip()
    # IP-адреса, для которых нужно показывать котов
    cat_ips = ['192.168.88.180', '192.168.88.105', '192.168.88.162', '192.168.88.137']
    show_cats = client_ip in cat_ips
    
    # Логирование для отладки
    print(f'[client-info] ========== CLIENT INFO REQUEST ==========')
    print(f'[client-info] Client IP: {client_ip}')
    print(f'[client-info] Show cats: {show_cats}')
    print(f'[client-info] Cat IPs list: {cat_ips}')
    print(f'[client-info] IP in list: {client_ip in cat_ips}')
    print(f'[client-info] X-Forwarded-For: {request.headers.get("X-Forwarded-For")}')
    print(f'[client-info] X-Real-IP: {request.headers.get("X-Real-IP")}')
    print(f'[client-info] CF-Connecting-IP: {request.headers.get("CF-Connecting-IP")}')
    print(f'[client-info] remote_addr: {request.remote_addr}')
    print(f'[client-info] All headers: {dict(request.headers)}')
    print(f'[client-info] =========================================')
    
    return jsonify({
        "ip": client_ip,
        "show_cats": show_cats,
        "debug": {
            "detected_ip": client_ip,
            "cat_ips": cat_ips,
            "is_in_list": client_ip in cat_ips
        }
    }), 200


# ============= API ENDPOINTS ДЛЯ АВТОРИЗАЦИИ =============

@app.route('/api/auth/register', methods=['POST'])
def register():
    """
    Регистрация нового пользователя (ОТКЛЮЧЕНА для обычных пользователей)
    Используйте скрипт create_user.py для создания пользователей
    """
    return jsonify({
        "success": False, 
        "error": "Регистрация отключена. Обратитесь к администратору для создания аккаунта."
    }), 403


@app.route('/api/auth/init-admin', methods=['POST'])
def init_admin():
    """
    Создание первого администратора (только если база пустая)
    POST /api/auth/init-admin
    Body: {
        "secret_key": "12345",
        "username": "polina",
        "password": "123",
        "email": "polina@agm.local"
    }
    
    ⚠️ ВАЖНО: Используйте только один раз для создания первого пользователя!
    После создания первого пользователя этот endpoint автоматически отключится.
    """
    try:
        # Проверяем, есть ли уже пользователи
        existing_users = User.query.all()
        if existing_users:
            return jsonify({
                "success": False,
                "error": "Пользователи уже существуют. Используйте /api/auth/login для входа."
            }), 403
        
        # Проверяем секретный ключ
        data = request.get_json()
        if not data:
            return jsonify({
                "success": False,
                "error": "Не получены данные. Убедитесь, что отправляете JSON с Content-Type: application/json"
            }), 400
        
        provided_secret = data.get('secret_key', '')
        expected_secret = os.environ.get('INIT_ADMIN_SECRET') or os.environ.get('SECRET_KEY', '')
        
        if not provided_secret or provided_secret != expected_secret:
            return jsonify({
                "success": False,
                "error": "Неверный секретный ключ"
            }), 401
        
        # Получаем данные пользователя
        username = data.get('username', 'polina').strip()
        password = data.get('password', '123')
        email = data.get('email', f'{username}@agm.local').strip()
        
        if not username or not password:
            return jsonify({
                "success": False,
                "error": "Имя пользователя и пароль обязательны"
            }), 400
        
        # Проверяем, не существует ли уже такой пользователь
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            return jsonify({
                "success": False,
                "error": f"Пользователь '{username}' уже существует"
            }), 400
        
        # Создаем администратора
        user = User(
            username=username,
            email=email,
            is_admin=True
        )
        user.set_password(password)
        
        db.session.add(user)
        db.session.commit()
        
        print(f"✅ Администратор '{username}' создан успешно!")
        
        return jsonify({
            "success": True,
            "message": f"Администратор '{username}' создан успешно!",
            "user": {
                "username": user.username,
                "email": user.email,
                "is_admin": user.is_admin
            }
        }), 201
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Ошибка создания администратора: {str(e)}")
        return jsonify({
            "success": False,
            "error": f"Ошибка создания пользователя: {str(e)}"
        }), 500


@app.route('/api/auth/login', methods=['POST'])
def login():
    """
    Вход пользователя
    POST /api/auth/login
    Body: {
        "username": "user123",
        "password": "password123"
    }
    """
    try:
        data = request.get_json()
        
        username = data.get('username', '').strip()
        password = data.get('password', '')
        
        if not username or not password:
            return jsonify({"success": False, "error": "Введите имя пользователя и пароль"}), 400
        
        # Поиск пользователя
        user = User.query.filter_by(username=username).first()
        
        if not user or not user.check_password(password):
            return jsonify({"success": False, "error": "Неверное имя пользователя или пароль"}), 401
        
        # Вход
        login_user(user, remember=True)
        session.permanent = True
        
        print(f"✅ Пользователь вошел: {username}")
        
        return jsonify({
            "success": True,
            "message": "Вход выполнен успешно",
            "user": user.to_dict()
        }), 200
        
    except Exception as e:
        print(f"❌ Ошибка входа: {str(e)}")
        return jsonify({"success": False, "error": "Ошибка сервера при входе"}), 500


@app.route('/api/auth/logout', methods=['POST'])
@login_required
def logout():
    """
    Выход пользователя
    POST /api/auth/logout
    """
    username = current_user.username
    logout_user()
    print(f"✅ Пользователь вышел: {username}")
    return jsonify({"success": True, "message": "Выход выполнен успешно"}), 200


@app.route('/api/auth/user', methods=['GET'])
def get_current_user():
    """
    Получить текущего пользователя
    GET /api/auth/user
    """
    if current_user.is_authenticated:
        return jsonify({
            "authenticated": True,
            "user": current_user.to_dict()
        }), 200
    else:
        return jsonify({"authenticated": False}), 200


# ============= API ENDPOINTS ДЛЯ СОХРАНЕННЫХ РЕЗУЛЬТАТОВ =============

@app.route('/api/results/save', methods=['POST'])
@login_required
def save_result():
    """
    Сохранить результат подбора насоса
    POST /api/results/save
    Body: {
        "title": "Название подбора",
        "flow": 100,
        "head": 10,
        "data": "{...}" // JSON строка с полными данными
    }
    """
    try:
        data = request.get_json()
        
        title = data.get('title', '').strip()
        if not title:
            title = f"Подбор от {datetime.now().strftime('%d.%m.%Y %H:%M')}"
        
        # Создание сохраненного результата
        saved_result = SavedResult(
            user_id=current_user.id,
            title=title,
            flow=data.get('flow'),
            head=data.get('head'),
            static_head=data.get('staticHead'),
            density=data.get('density'),
            pump_type=data.get('pumpType'),
            selected_pump=data.get('selectedPump'),
            data=json.dumps(data.get('data', {}), ensure_ascii=False)
        )
        
        db.session.add(saved_result)
        db.session.commit()
        
        print(f"✅ Результат сохранен (ID: {saved_result.id}) пользователем {current_user.username}")
        
        return jsonify({
            "success": True,
            "message": "Результат успешно сохранен",
            "result": saved_result.to_dict()
        }), 201
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Ошибка сохранения результата: {str(e)}")
        return jsonify({"success": False, "error": "Ошибка при сохранении результата"}), 500


@app.route('/api/results', methods=['GET'])
@login_required
def get_saved_results():
    """
    Получить сохраненные результаты
    Администратор (polina) видит результаты всех пользователей
    Обычные пользователи видят только свои результаты
    GET /api/results
    """
    try:
        # Если пользователь администратор - показать все результаты
        if current_user.is_admin:
            results = SavedResult.query.order_by(SavedResult.created_at.desc()).all()
            print(f"👑 Администратор {current_user.username} получает ВСЕ результаты")
        else:
            results = SavedResult.query.filter_by(user_id=current_user.id).order_by(SavedResult.created_at.desc()).all()
        
        # Добавляем имя владельца к каждому результату
        results_data = []
        for result in results:
            result_dict = result.to_dict()
            # Получаем имя владельца
            owner = User.query.get(result.user_id)
            result_dict['owner_username'] = owner.username if owner else 'Неизвестный'
            results_data.append(result_dict)
        
        return jsonify({
            "success": True,
            "results": results_data,
            "count": len(results),
            "is_admin": current_user.is_admin
        }), 200
        
    except Exception as e:
        print(f"❌ Ошибка получения результатов: {str(e)}")
        return jsonify({"success": False, "error": "Ошибка при получении результатов"}), 500


@app.route('/api/results/<int:result_id>', methods=['GET'])
@login_required
def get_saved_result(result_id):
    """
    Получить конкретный сохраненный результат
    Администратор может получить любой результат
    GET /api/results/<id>
    """
    try:
        # Администратор может получить любой результат
        if current_user.is_admin:
            result = SavedResult.query.filter_by(id=result_id).first()
        else:
            result = SavedResult.query.filter_by(id=result_id, user_id=current_user.id).first()
        
        if not result:
            return jsonify({"success": False, "error": "Результат не найден"}), 404
        
        return jsonify({
            "success": True,
            "result": result.to_dict()
        }), 200
        
    except Exception as e:
        print(f"❌ Ошибка получения результата: {str(e)}")
        return jsonify({"success": False, "error": "Ошибка при получении результата"}), 500


@app.route('/api/results/<int:result_id>', methods=['DELETE'])
@login_required
def delete_saved_result(result_id):
    """
    Удалить сохраненный результат
    Администратор может удалить любой результат
    DELETE /api/results/<id>
    """
    try:
        # Администратор может удалить любой результат
        if current_user.is_admin:
            result = SavedResult.query.filter_by(id=result_id).first()
        else:
            result = SavedResult.query.filter_by(id=result_id, user_id=current_user.id).first()
        
        if not result:
            return jsonify({"success": False, "error": "Результат не найден"}), 404
        
        db.session.delete(result)
        db.session.commit()
        
        print(f"✅ Результат удален (ID: {result_id}) пользователем {current_user.username}")
        
        return jsonify({
            "success": True,
            "message": "Результат успешно удален"
        }), 200
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Ошибка удаления результата: {str(e)}")
        return jsonify({"success": False, "error": "Ошибка при удалении результата"}), 500


@app.route('/api/generate-tkp', methods=['POST'])
@login_required
def generate_tkp():
    """
    Генерация технико-коммерческого предложения
    POST /api/generate-tkp
    Требуется авторизация
    FormData: {
        "tech_pdf": File (PDF технического описания),
        "customer": "Название заказчика",
        "pump_name": "Название насоса",
        "price": "100" (цена насоса)
    }
    """
    try:
        # Проверяем наличие необходимых данных
        if 'tech_pdf' not in request.files:
            return jsonify({"error": "Не указан PDF технического описания"}), 400
        
        customer = request.form.get('customer', '').strip()
        pump_name = request.form.get('pump_name', '').strip()
        price_str = request.form.get('price', '100').strip()
        pump_type = request.form.get('pump_type', '').strip()  # Тип насоса: Канализационный, Шламовый, Дренажный
        
        if not customer:
            return jsonify({"error": "Не указан заказчик"}), 400
        
        try:
            price = float(price_str)
        except ValueError:
            price = 100.0
        
        # Вычисляем 22% от цены и итоговую цену
        tax_amount = price * 0.22
        total_price = price + tax_amount
        
        # Получаем сегодняшнюю дату
        today_date = datetime.now().strftime('%d.%m.%Y')
        
        # Генерируем порядковый номер ТКП
        def get_next_tkp_number():
            """Получает следующий порядковый номер ТКП"""
            counter_file = os.path.join(os.path.dirname(__file__), 'tkp_counter.txt')
            try:
                if os.path.exists(counter_file):
                    with open(counter_file, 'r', encoding='utf-8') as f:
                        current_number = int(f.read().strip())
                else:
                    current_number = 0
            except (ValueError, FileNotFoundError):
                current_number = 0
            
            # Увеличиваем номер
            next_number = current_number + 1
            
            # Сохраняем новый номер
            with open(counter_file, 'w', encoding='utf-8') as f:
                f.write(str(next_number))
            
            # Форматируем номер с ведущими нулями (6 цифр)
            return f'{next_number:06d}'
        
        tkp_number = get_next_tkp_number()
        
        # Проверяем наличие файла КП.docx
        kp_docx_path = os.path.join(os.path.dirname(__file__), 'КП.docx')
        if not os.path.exists(kp_docx_path):
            return jsonify({"error": "Файл КП.docx не найден"}), 404
        
        # Создаем временные файлы
        with tempfile.TemporaryDirectory() as temp_dir:
            tech_pdf_file = request.files['tech_pdf']
            tech_pdf_path = os.path.join(temp_dir, 'tech.pdf')
            tech_pdf_file.save(tech_pdf_path)
            
            # Копируем КП.docx во временную директорию
            modified_docx_path = os.path.join(temp_dir, 'КП_modified.docx')
            
            # Определяем замены текста (используется в обоих блоках)
            # ВАЖНО: Сначала заменяем более длинные строки, чтобы избежать частичных замен
            # Например, "ЦЕНА + 22%" должен заменяться до того, как "ЦЕНА" заменится отдельно
            # Добавляем разные варианты написания для учета разных пробелов
            replacements = {
                'ЦЕНА + 22%': f'{total_price:.2f}',
                'ЦЕНА +22%': f'{total_price:.2f}',
                'ЦЕНА+ 22%': f'{total_price:.2f}',
                'ЦЕНА+22%': f'{total_price:.2f}',
                f'{price:.2f} + 22%': f'{total_price:.2f}',  # Если ЦЕНА уже заменилась
                f'{price:.2f} +22%': f'{total_price:.2f}',
                f'{price:.2f}+ 22%': f'{total_price:.2f}',
                f'{price:.2f}+22%': f'{total_price:.2f}',
                '22% ОТ ЦЕНЫ': f'{tax_amount:.2f}',
                '22% от цены': f'{tax_amount:.2f}',
                f'22% от {price:.2f}': f'{tax_amount:.2f}',
                'НОМЕР': tkp_number,  # Порядковый номер ТКП
                'ДАТА': today_date,
                'ЗАКАЗЧИК': customer,
                'НАЗВАНИЕ': pump_name,
                'ЦЕНА': f'{price:.2f}',
                'ТИП': pump_type if pump_type else ''  # Тип насоса: Канализационный, Шламовый, Дренажный
            }
            
            # Для работы с Word документами нужна библиотека python-docx
            try:
                from docx import Document
                
                # Загружаем документ
                doc = Document(kp_docx_path)
                
                # Функция для замены текста в параграфе
                def replace_in_paragraph(paragraph):
                    # Сначала получаем полный текст со всеми runs
                    full_text = paragraph.text
                    if not full_text:
                        return
                    
                    # Проверяем, нужно ли заменять
                    # ВАЖНО: Заменяем более длинные фразы ПЕРВЫМИ, чтобы избежать частичных замен
                    # Порядок в словаре replacements уже правильный (длинные строки первыми)
                    needs_replace = False
                    replaced_text = full_text
                    
                    # Создаем список замен в правильном порядке (от длинных к коротким)
                    sorted_replacements = sorted(replacements.items(), key=lambda x: len(x[0]), reverse=True)
                    
                    for old_text, new_text in sorted_replacements:
                        if old_text in replaced_text:
                            needs_replace = True
                            replaced_text = replaced_text.replace(old_text, new_text)
                    
                    if needs_replace:
                        # Сохраняем стили первого run
                        if paragraph.runs:
                            first_run = paragraph.runs[0]
                            # Очищаем все runs
                            for run in paragraph.runs:
                                run.text = ''
                            # Восстанавливаем текст в первом run
                            first_run.text = replaced_text
                        else:
                            # Если нет runs, создаем новый
                            paragraph.add_run(replaced_text)
                
                # Замена в параграфах
                for paragraph in doc.paragraphs:
                    replace_in_paragraph(paragraph)
                
                # Замена в таблицах
                for table in doc.tables:
                    for row in table.rows:
                        for cell in row.cells:
                            for paragraph in cell.paragraphs:
                                replace_in_paragraph(paragraph)
                
                # Сохраняем модифицированный документ
                doc.save(modified_docx_path)
                print(f"✅ DOCX документ сохранен: {modified_docx_path}")
                
                # Проверяем, что файл создан и не пустой
                if not os.path.exists(modified_docx_path):
                    raise FileNotFoundError(f"Файл не был создан: {modified_docx_path}")
                if os.path.getsize(modified_docx_path) == 0:
                    raise ValueError(f"Файл пустой: {modified_docx_path}")
                
            except Exception as e:
                # Логируем ошибку для отладки
                print(f"⚠️ Ошибка при использовании python-docx: {str(e)}")
                import traceback
                traceback.print_exc()
                
                # Если python-docx не сработал, продолжаем с zipfile методом
                # Если python-docx не установлен или произошла ошибка, пробуем использовать простую замену через zipfile
                import zipfile
                import xml.etree.ElementTree as ET
                import shutil
                
                # Создаем временный файл для нового архива
                temp_docx_path = os.path.join(temp_dir, 'temp_docx.docx')
                
                # Сначала читаем все данные из исходного файла
                file_contents = {}
                with zipfile.ZipFile(kp_docx_path, 'r') as source_docx:
                    for item in source_docx.infolist():
                        file_contents[item.filename] = source_docx.read(item.filename)
                
                # Модифицируем document.xml
                if 'word/document.xml' in file_contents:
                    xml_content = file_contents['word/document.xml']
                    try:
                        # Декодируем из байтов
                        if isinstance(xml_content, bytes):
                            xml_str = xml_content.decode('utf-8')
                        else:
                            xml_str = xml_content
                        
                        # Парсим XML
                        root = ET.fromstring(xml_str)
                        
                        # Заменяем текст в XML
                        def replace_text_in_xml(elem):
                            if elem.text:
                                for old_text, new_text in replacements.items():
                                    if old_text in elem.text:
                                        elem.text = elem.text.replace(old_text, new_text)
                            if elem.tail:
                                for old_text, new_text in replacements.items():
                                    if old_text in elem.tail:
                                        elem.tail = elem.tail.replace(old_text, new_text)
                            for child in elem:
                                replace_text_in_xml(child)
                        
                        replace_text_in_xml(root)
                        
                        # Сохраняем измененный XML обратно
                        xml_bytes = ET.tostring(root, encoding='utf-8', xml_declaration=True)
                        file_contents['word/document.xml'] = xml_bytes
                    except Exception as xml_error:
                        print(f"⚠️ Ошибка обработки XML: {xml_error}")
                        # Пробуем простую текстовую замену (от длинных к коротким)
                        xml_str = xml_content.decode('utf-8') if isinstance(xml_content, bytes) else xml_content
                        sorted_replacements = sorted(replacements.items(), key=lambda x: len(x[0]), reverse=True)
                        for old_text, new_text in sorted_replacements:
                            xml_str = xml_str.replace(old_text, new_text)
                        file_contents['word/document.xml'] = xml_str.encode('utf-8')
                
                # Записываем новый архив
                with zipfile.ZipFile(temp_docx_path, 'w', zipfile.ZIP_DEFLATED) as new_docx:
                    for filename, content in file_contents.items():
                        new_docx.writestr(filename, content)
                
                # Перемещаем временный файл в финальный
                shutil.move(temp_docx_path, modified_docx_path)
                print(f"✅ DOCX документ сохранен через zipfile: {modified_docx_path}")
            
            # Проверяем, что DOCX файл создан и доступен перед конвертацией
            if not os.path.exists(modified_docx_path):
                return jsonify({"error": f"Не удалось создать DOCX файл: {modified_docx_path}"}), 500
            
            if os.path.getsize(modified_docx_path) == 0:
                return jsonify({"error": f"Созданный DOCX файл пустой: {modified_docx_path}"}), 500
            
            print(f"✅ DOCX файл готов для конвертации: {modified_docx_path} ({os.path.getsize(modified_docx_path)} байт)")
            
            # Конвертируем DOCX в PDF
            # LibreOffice создает файл с именем на основе исходного файла
            kp_pdf_path = os.path.join(temp_dir, 'КП_modified.pdf')
            
            # Пробуем использовать LibreOffice для конвертации
            libreoffice_paths = [
                'libreoffice',
                'soffice',
                r'C:\Program Files\LibreOffice\program\soffice.exe',
                r'C:\Program Files (x86)\LibreOffice\program\soffice.exe'
            ]
            
            libreoffice_found = False
            for lo_path in libreoffice_paths:
                try:
                    result = subprocess.run(
                        [lo_path, '--headless', '--convert-to', 'pdf', '--outdir', temp_dir, modified_docx_path],
                        capture_output=True,
                        timeout=30,
                        check=False
                    )
                    # LibreOffice создает файл с тем же именем, но с расширением .pdf
                    if result.returncode == 0:
                        # Проверяем несколько возможных имен файлов
                        possible_paths = [
                            os.path.join(temp_dir, 'КП_modified.pdf'),
                            os.path.join(temp_dir, 'kp_modified.pdf'),
                            os.path.join(temp_dir, 'kp.pdf')
                        ]
                        for path in possible_paths:
                            if os.path.exists(path):
                                kp_pdf_path = path
                                libreoffice_found = True
                                break
                        if libreoffice_found:
                            break
                except (FileNotFoundError, subprocess.TimeoutExpired):
                    continue
            
            if not libreoffice_found:
                pdf_converted = False
                conversion_error = ""
                
                # Сначала пробуем использовать MS Word через COM (только Windows) - самый надежный способ
                try:
                    import sys
                    if sys.platform == 'win32':
                        try:
                            import win32com.client
                            import pythoncom
                            
                            print("🔄 Пробую использовать MS Word через COM...")
                            
                            # Инициализируем COM (критически важно для работы с COM объектами)
                            pythoncom.CoInitialize()
                            
                            # Запускаем Word
                            word = None
                            try:
                                word = win32com.client.Dispatch("Word.Application")
                                word.Visible = False
                                word.DisplayAlerts = 0  # Отключаем предупреждения
                                
                                # Открываем документ (нужно использовать полный путь и правильные слеши)
                                doc_path = os.path.abspath(modified_docx_path).replace('/', '\\')
                                print(f"📄 Открываю документ: {doc_path}")
                                
                                if not os.path.exists(doc_path):
                                    raise FileNotFoundError(f"Файл не найден: {doc_path}")
                                
                                # Пробуем открыть документ с различными параметрами
                                try:
                                    doc = word.Documents.Open(
                                        FileName=doc_path,
                                        ReadOnly=True,
                                        ConfirmConversions=False,
                                        AddToRecentFiles=False
                                    )
                                except Exception as open_err:
                                    # Если не получилось с ReadOnly, пробуем без него
                                    print(f"⚠️ Не удалось открыть с ReadOnly, пробую без ReadOnly...")
                                    doc = word.Documents.Open(
                                        FileName=doc_path,
                                        ConfirmConversions=False,
                                        AddToRecentFiles=False
                                    )
                                
                                # Сохраняем как PDF
                                pdf_path = os.path.abspath(kp_pdf_path).replace('/', '\\')
                                print(f"💾 Сохраняю PDF: {pdf_path}")
                                
                                # Убеждаемся, что директория существует
                                pdf_dir = os.path.dirname(pdf_path)
                                if not os.path.exists(pdf_dir):
                                    os.makedirs(pdf_dir, exist_ok=True)
                                
                                doc.SaveAs2(
                                    FileName=pdf_path,
                                    FileFormat=17  # wdFormatPDF = 17
                                )
                                
                                # Закрываем документ и Word
                                doc.Close(False)  # False = не сохранять изменения
                                word.Quit(SaveChanges=False)
                                word = None
                                
                                # Небольшая задержка для завершения записи файла
                                import time
                                time.sleep(0.5)
                                
                                # Проверяем, что файл создан
                                if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0:
                                    pdf_converted = True
                                    print(f"✅ PDF успешно создан через MS Word ({os.path.getsize(pdf_path)} байт)")
                                else:
                                    conversion_error += "PDF файл не создан или пустой. "
                                    print("⚠️ PDF файл не создан или пустой")
                                    
                            except Exception as e:
                                error_msg = str(e)
                                conversion_error += f"Ошибка MS Word COM: {error_msg}. "
                                print(f"⚠️ Ошибка при использовании MS Word: {error_msg}")
                                import traceback
                                traceback.print_exc()
                            finally:
                                # Убеждаемся, что Word закрыт
                                if word:
                                    try:
                                        word.Quit(SaveChanges=False)
                                    except:
                                        pass
                                        
                        except ImportError as ie:
                            conversion_error += "win32com не доступен. "
                            print(f"⚠️ win32com не установлен: {ie}")
                        except Exception as e:
                            conversion_error += f"Ошибка COM: {str(e)}. "
                            print(f"⚠️ Ошибка при попытке использовать MS Word: {str(e)}")
                            import traceback
                            traceback.print_exc()
                    else:
                        conversion_error += "Не Windows система. "
                except Exception as e:
                    conversion_error += f"Системная ошибка: {str(e)}. "
                    print(f"⚠️ Ошибка при проверке MS Word: {str(e)}")
                    import traceback
                    traceback.print_exc()
                
                # Если MS Word не сработал, пробуем docx2pdf (он сам попробует найти LibreOffice или MS Word)
                if not pdf_converted:
                    try:
                        from docx2pdf import convert
                        print("🔄 Пробую использовать docx2pdf...")
                        convert(modified_docx_path, kp_pdf_path)
                        if os.path.exists(kp_pdf_path) and os.path.getsize(kp_pdf_path) > 0:
                            pdf_converted = True
                            print("✅ PDF создан через docx2pdf")
                        else:
                            conversion_error += "docx2pdf: файл не создан. "
                    except ImportError:
                        conversion_error += "docx2pdf не установлен. "
                        print("⚠️ Библиотека docx2pdf не установлена")
                    except Exception as e:
                        conversion_error += f"docx2pdf ошибка: {str(e)}. "
                        print(f"⚠️ Ошибка docx2pdf: {str(e)}")
                        import traceback
                        traceback.print_exc()
                
                # Если ничего не сработало, возвращаем ошибку с деталями
                if not pdf_converted:
                    error_msg = (
                        f"Не удалось конвертировать DOCX в PDF.\n\n"
                        f"Детали ошибок: {conversion_error}\n\n"
                        f"Рекомендации:\n"
                        f"1. Убедитесь, что MS Word установлен и доступен\n"
                        f"2. Попробуйте открыть Word вручную и проверить, что он работает\n"
                        f"3. Установите LibreOffice (рекомендуется): https://www.libreoffice.org/\n"
                        f"4. Проверьте логи сервера для подробностей"
                    )
                    return jsonify({"error": error_msg}), 500
            
            # Объединяем PDF файлы
            try:
                from PyPDF2 import PdfReader, PdfWriter
                
                writer = PdfWriter()
                
                # Добавляем страницы из КП ПЕРВЫМИ (страница КП должна быть первой)
                if os.path.exists(kp_pdf_path):
                    with open(kp_pdf_path, 'rb') as kp_pdf:
                        kp_reader = PdfReader(kp_pdf)
                        for page in kp_reader.pages:
                            writer.add_page(page)
                
                # Затем добавляем страницы из технического описания
                with open(tech_pdf_path, 'rb') as tech_pdf:
                    tech_reader = PdfReader(tech_pdf)
                    for page in tech_reader.pages:
                        writer.add_page(page)
                
                # Сохраняем объединенный PDF в память
                output_buffer = BytesIO()
                writer.write(output_buffer)
                output_buffer.seek(0)
                
                return send_file(
                    output_buffer,
                    mimetype='application/pdf',
                    as_attachment=True,
                    download_name='Технико-коммерческое_предложение.pdf'
                )
                
            except ImportError:
                # Пробуем использовать pypdf
                try:
                    from pypdf import PdfReader, PdfWriter
                    
                    writer = PdfWriter()
                    
                    # Добавляем страницы из КП ПЕРВЫМИ (страница КП должна быть первой)
                    if os.path.exists(kp_pdf_path):
                        with open(kp_pdf_path, 'rb') as kp_pdf:
                            kp_reader = PdfReader(kp_pdf)
                            for page in kp_reader.pages:
                                writer.add_page(page)
                    
                    # Затем добавляем страницы из технического описания
                    with open(tech_pdf_path, 'rb') as tech_pdf:
                        tech_reader = PdfReader(tech_pdf)
                        for page in tech_reader.pages:
                            writer.add_page(page)
                    
                    # Сохраняем объединенный PDF в память
                    output_buffer = BytesIO()
                    writer.write(output_buffer)
                    output_buffer.seek(0)
                    
                    return send_file(
                        output_buffer,
                        mimetype='application/pdf',
                        as_attachment=True,
                        download_name='Технико-коммерческое_предложение.pdf'
                    )
                    
                except ImportError:
                    return jsonify({
                        "error": "Не установлена библиотека для работы с PDF. Установите: pip install PyPDF2 или pip install pypdf"
                    }), 500
            
    except Exception as e:
        print(f"❌ Ошибка при генерации ТКП: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Ошибка при генерации ТКП: {str(e)}"}), 500


@app.route('/api/find-drawing', methods=['POST'])
def find_drawing():
    """
    Поиск подходящего габаритного чертежа для насоса
    POST /api/find-drawing
    Body: {
        "pump_name": "Название насоса"
    }
    Returns: {
        "found": true/false,
        "filename": "имя файла" (если найден)
    }
    """
    try:
        data = request.get_json()
        pump_name = data.get('pump_name', '').strip()
        
        if not pump_name:
            return jsonify({"found": False}), 200
        
        # Путь к папке с чертежами
        drawings_dir = os.path.join(os.path.dirname(__file__), 'Установы')
        
        if not os.path.exists(drawings_dir):
            return jsonify({"found": False}), 200
        
        # Получаем все PDF файлы из папки
        pdf_files = [f for f in os.listdir(drawings_dir) if f.lower().endswith('.pdf')]
        
        if not pdf_files:
            return jsonify({"found": False}), 200
        
        # Нормализуем название насоса для сравнения
        # Убираем лишние части: "В", числа после точки (180), последние числа (4 9)
        # Пример: "АГМ В КнП 3153.180 СН 4 9" -> "АГМ КнП 3153 СН"
        def normalize_pump_name(name):
            # Убираем "В" (отдельное слово)
            normalized = name.replace(' В ', ' ').replace('В ', '').strip()
            
            # Убираем числа после точки (например, ".180")
            import re
            normalized = re.sub(r'\.\d+', '', normalized)
            
            # Убираем последние числа в конце (например, "4 9")
            # Ищем паттерн: пробел, число, возможно еще пробел и число в конце
            normalized = re.sub(r'\s+\d+(\s+\d+)*$', '', normalized).strip()
            
            # Убираем лишние пробелы
            normalized = ' '.join(normalized.split())
            
            return normalized
        
        # Нормализуем название насоса
        normalized_pump_name = normalize_pump_name(pump_name)
        
        # Ищем подходящий файл
        # Логика: нормализованное название файла должно содержаться в нормализованном названии насоса
        # Если несколько совпадений, выбираем самое длинное (более специфичное)
        matching_files = []
        
        for pdf_file in pdf_files:
            # Убираем расширение .pdf
            file_name_without_ext = pdf_file[:-4]  # Убираем ".pdf"
            
            # Нормализуем название файла (убираем лишние пробелы)
            normalized_file_name = ' '.join(file_name_without_ext.split())
            
            # Проверяем, содержится ли нормализованное название файла в нормализованном названии насоса
            if normalized_file_name in normalized_pump_name:
                matching_files.append((pdf_file, len(normalized_file_name)))
        
        if not matching_files:
            return jsonify({"found": False}), 200
        
        # Сортируем по длине (самое длинное первым) и берем первый
        matching_files.sort(key=lambda x: x[1], reverse=True)
        best_match = matching_files[0][0]
        
        return jsonify({
            "found": True,
            "filename": best_match
        }), 200
        
    except Exception as e:
        print(f"❌ Ошибка при поиске чертежа: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"found": False}), 200


@app.route('/api/get-drawing-pdf', methods=['GET'])
def get_drawing_pdf():
    """
    Получение PDF файла чертежа
    GET /api/get-drawing-pdf?filename=имя_файла
    """
    try:
        filename = request.args.get('filename', '')
        
        if not filename:
            return jsonify({"error": "Не указано имя файла"}), 400
        
        # Проверяем безопасность имени файла (только буквы, цифры, пробелы, дефисы, точки)
        if not all(c.isalnum() or c in (' ', '-', '.', '_') for c in filename):
            return jsonify({"error": "Некорректное имя файла"}), 400
        
        # Путь к файлу
        file_path = os.path.join(os.path.dirname(__file__), 'Установы', filename)
        
        if not os.path.exists(file_path):
            return jsonify({"error": "Файл не найден"}), 404
        
        # Проверяем, что файл действительно PDF
        if not filename.lower().endswith('.pdf'):
            return jsonify({"error": "Файл не является PDF"}), 400
        
        # Возвращаем первую страницу PDF
        try:
            from pypdf import PdfReader, PdfWriter
        except ImportError:
            try:
                from PyPDF2 import PdfReader, PdfWriter
            except ImportError:
                # Если библиотеки нет, возвращаем весь файл
                return send_file(
                    file_path,
                    mimetype='application/pdf',
                    as_attachment=False
                )
        
        # Извлекаем первую страницу
        reader = PdfReader(file_path)
        if len(reader.pages) == 0:
            return jsonify({"error": "PDF файл пустой"}), 400
        
        writer = PdfWriter()
        writer.add_page(reader.pages[0])
        
        output_buffer = BytesIO()
        writer.write(output_buffer)
        output_buffer.seek(0)
        
        return send_file(
            output_buffer,
            mimetype='application/pdf',
            as_attachment=False
        )
        
    except Exception as e:
        print(f"❌ Ошибка при получении чертежа: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Ошибка при получении чертежа: {str(e)}"}), 500


@app.route('/api/generate-tp', methods=['POST'])
def generate_tp():
    """
    Генерация страницы технических характеристик из ТП.docx
    POST /api/generate-tp
    Body: {
        "specData": "JSON строка с данными из таблицы характеристик"
    }
    """
    try:
        data = request.get_json()
        if not data or 'specData' not in data:
            return jsonify({"error": "Не указаны данные характеристик"}), 400
        
        # Парсим данные характеристик
        import json
        spec_data = json.loads(data.get('specData', '{}'))
        
        # Проверяем наличие файла ТП.docx
        tp_docx_path = os.path.join(os.path.dirname(__file__), 'ТП.docx')
        if not os.path.exists(tp_docx_path):
            return jsonify({"error": "Файл ТП.docx не найден"}), 404
        
        # Создаем временные файлы
        with tempfile.TemporaryDirectory() as temp_dir:
            modified_docx_path = os.path.join(temp_dir, 'ТП_modified.docx')
            
            # Определяем замены текста для ТП.docx
            # Параметры в документе написаны заглавными буквами (плейсхолдеры)
            # Заменяем только заглавные буквы, не названия параметров
            replacements = {}
            
            # НАЗВАНИЕ - название насоса (добавляем первым, чтобы не конфликтовать с другими заменами)
            if 'НАЗВАНИЕ' in spec_data:
                replacements['НАЗВАНИЕ'] = str(spec_data['НАЗВАНИЕ'])
            
            # Заменяем параметры из таблицы
            # В ТП.docx плейсхолдеры написаны заглавными буквами
            for param, value in spec_data.items():
                # КПД не заменяется, вместо него используются ЭФФ1 и ЭФФ2
                if 'КПД' in param.upper() or 'ЭФФЕКТИВНОСТЬ' in param.upper():
                    continue  # Пропускаем КПД, он заменяется отдельно через ЭФФ1/ЭФФ2
                
                # Пропускаем НАЗВАНИЕ, оно уже добавлено выше
                if 'НАЗВАНИЕ' in param.upper():
                    continue
                
                # Ищем параметр ТОЛЬКО в заглавных буквах (плейсхолдер)
                param_upper = param.upper()
                replacements[param_upper] = str(value)
                
                # Также добавляем варианты с убранием единиц измерения и форматированием
                # Например, "ПОДАЧА", "ПОДАЧА М3/Ч" и т.д.
                if ' (оптимальная)' in param:
                    param_clean = param.replace(' (оптимальная)', '').upper()
                    replacements[param_clean + ' (ОПТИМАЛЬНАЯ)'] = str(value)
                    replacements[param_clean + ' (ОПТИМАЛЬНАЯ ТОЧКА)'] = str(value)
            
            # Специальная обработка КПД: заменяем на ЭФФ1 (рабочая) и ЭФФ2 (оптимальная)
            if 'ЭФФ1' in spec_data:
                replacements['ЭФФ1'] = str(spec_data['ЭФФ1'])
                replacements['КПД (РАБОЧАЯ)'] = str(spec_data['ЭФФ1'])
                replacements['КПД РАБОЧАЯ'] = str(spec_data['ЭФФ1'])
            if 'ЭФФ2' in spec_data:
                replacements['ЭФФ2'] = str(spec_data['ЭФФ2'])
                replacements['КПД (ОПТИМАЛЬНАЯ)'] = str(spec_data['ЭФФ2'])
                replacements['КПД ОПТИМАЛЬНАЯ'] = str(spec_data['ЭФФ2'])
            
            # Добавляем дополнительные замены для удобства
            # Диаметр
            if 'Диаметр' in spec_data:
                replacements['ДИАМЕТР'] = str(spec_data['Диаметр'])
            if 'Диаметр рабочего колеса' in spec_data:
                replacements['ДИАМЕТР РАБОЧЕГО КОЛЕСА'] = str(spec_data['Диаметр рабочего колеса'])
            
            # Масса
            if 'Масса' in spec_data:
                replacements['МАССА'] = str(spec_data['Масса'])
            
            # ДЛИНА (длина кабеля) - БЕЗ единиц измерения
            if 'ДЛИНА' in spec_data:
                replacements['ДЛИНА'] = str(spec_data['ДЛИНА'])
            if 'Длина' in spec_data:
                replacements['ДЛИНА'] = str(spec_data['Длина'])
            if 'Длина кабеля' in spec_data:
                replacements['ДЛИНА КАБЕЛЯ'] = str(spec_data['Длина кабеля'])
            
            # НАПРЯЖЕНИЕ - БЕЗ единиц измерения
            if 'НАПРЯЖЕНИЕ' in spec_data:
                replacements['НАПРЯЖЕНИЕ'] = str(spec_data['НАПРЯЖЕНИЕ'])
            if 'Напряжение' in spec_data:
                replacements['НАПРЯЖЕНИЕ'] = str(spec_data['Напряжение'])
            
            # EX - взрывозащита
            if 'EX' in spec_data:
                replacements['EX'] = str(spec_data['EX'])
            if 'Взрывозащита' in spec_data:
                ex_value = str(spec_data['Взрывозащита']).lower()
                if 'да' in ex_value or 'yes' in ex_value:
                    replacements['EX'] = 'да'
                else:
                    replacements['EX'] = 'нет'
            
            # Частота
            if 'Частота' in spec_data:
                replacements['ЧАСТОТА'] = str(spec_data['Частота'])
            
            # Мощность
            if 'МОЩНОСТЬ' in spec_data:
                replacements['МОЩНОСТЬ'] = str(spec_data['МОЩНОСТЬ'])
            if 'Мощность' in spec_data:
                replacements['МОЩНОСТЬ'] = str(spec_data['Мощность'])
            
            # Полюсы
            if 'Полюсы' in spec_data:
                replacements['ПОЛЮСЫ'] = str(spec_data['Полюсы'])
            if 'Число полюсов' in spec_data:
                replacements['ЧИСЛО ПОЛЮСОВ'] = str(spec_data['Число полюсов'])
            
            # Изоляция
            if 'Изоляция' in spec_data:
                replacements['ИЗОЛЯЦИЯ'] = str(spec_data['Изоляция'])
            if 'Класс изоляции' in spec_data:
                replacements['КЛАСС ИЗОЛЯЦИИ'] = str(spec_data['Класс изоляции'])
            
            # Защита (IP класс)
            if 'Защита' in spec_data:
                replacements['ЗАЩИТА'] = str(spec_data['Защита'])
            
            # ТОК - БЕЗ единиц измерения
            if 'ТОК' in spec_data:
                replacements['ТОК'] = str(spec_data['ТОК'])
            if 'Ток' in spec_data:
                replacements['ТОК'] = str(spec_data['Ток'])
            if 'Номинальный ток' in spec_data:
                replacements['НОМИНАЛЬНЫЙ ТОК'] = str(spec_data['Номинальный ток'])
            
            # УЛИТКА - материал корпуса насоса
            if 'УЛИТКА' in spec_data:
                replacements['УЛИТКА'] = str(spec_data['УЛИТКА'])
            if 'Материал корпуса насоса (улитка)' in spec_data:
                replacements['УЛИТКА'] = str(spec_data['Материал корпуса насоса (улитка)'])
            
            # ВАЛ - материал вала
            if 'ВАЛ' in spec_data:
                replacements['ВАЛ'] = str(spec_data['ВАЛ'])
            if 'Материал вала' in spec_data:
                replacements['ВАЛ'] = str(spec_data['Материал вала'])
            
            # ДАТЧИКИ - список выбранных датчиков
            if 'ДАТЧИКИ' in spec_data:
                replacements['ДАТЧИКИ'] = str(spec_data['ДАТЧИКИ'])
            
            # ПЧ - двигатель под частотный преобразователь
            if 'ПЧ' in spec_data:
                replacements['ПЧ'] = str(spec_data['ПЧ'])
            
            # УСТАНОВКА - тип установки
            if 'УСТАНОВКА' in spec_data:
                replacements['УСТАНОВКА'] = str(spec_data['УСТАНОВКА'])
            
            # МАТЕРИАЛ - материал вторичных уплотнений
            # Если есть аксессуары, добавляем их под материалом
            if 'МАТЕРИАЛ' in spec_data:
                material_value = str(spec_data['МАТЕРИАЛ'])
                # Если есть аксессуары, добавляем их после материала
                if 'АКСЕССУАРЫ' in spec_data and spec_data['АКСЕССУАРЫ']:
                    accessories_value = str(spec_data['АКСЕССУАРЫ'])
                    # Объединяем материал и аксессуары (аксессуары на новой строке или через разделитель)
                    replacements['МАТЕРИАЛ'] = f"{material_value}\n{accessories_value}"
                else:
                    replacements['МАТЕРИАЛ'] = material_value
            
            # АКСЕССУАРЫ - список выбранных аксессуаров (отдельно, если нужно)
            if 'АКСЕССУАРЫ' in spec_data:
                replacements['АКСЕССУАРЫ'] = str(spec_data['АКСЕССУАРЫ'])
            
            # Если есть аксессуары, добавляем их после материала вторичных уплотнений
            # Ищем плейсхолдер "МАТЕРИАЛ" и добавляем после него аксессуары
            if 'АКСЕССУАРЫ' in spec_data and 'МАТЕРИАЛ' in spec_data:
                # Создаем комбинированное значение: материал + аксессуары
                material_value = str(spec_data['МАТЕРИАЛ'])
                accessories_value = str(spec_data['АКСЕССУАРЫ'])
                # Добавляем аксессуары после материала с переносом строки или разделителем
                combined_value = f"{material_value}\n{accessories_value}"
                # Заменяем МАТЕРИАЛ на комбинированное значение
                replacements['МАТЕРИАЛ'] = combined_value
                # Также добавляем вариант с переносом строки в разных форматах
                replacements['МАТЕРИАЛ\nАКСЕССУАРЫ'] = combined_value
                replacements['МАТЕРИАЛ АКСЕССУАРЫ'] = combined_value
            
            # Обрабатываем документ аналогично КП.docx
            try:
                from docx import Document
                
                doc = Document(tp_docx_path)
                
                # Функция для замены текста в параграфе
                # Заменяем ТОЛЬКО полностью заглавные слова/фразы (плейсхолдеры во втором столбце)
                def replace_in_paragraph(paragraph):
                    full_text = paragraph.text
                    if not full_text:
                        return
                    
                    needs_replace = False
                    replaced_text = full_text
                    
                    # Сортируем замены по длине (от длинных к коротким)
                    sorted_replacements = sorted(replacements.items(), key=lambda x: len(x[0]), reverse=True)
                    
                    # Заменяем только полностью заглавные слова/фразы (плейсхолдеры)
                    import re
                    for old_text, new_text in sorted_replacements:
                        # Ищем все вхождения (без учета регистра)
                        pattern = re.escape(old_text)
                        # Находим все совпадения
                        matches = list(re.finditer(pattern, replaced_text, re.IGNORECASE))
                        
                        # Обрабатываем в обратном порядке, чтобы не сместить индексы
                        for match in reversed(matches):
                            start, end = match.span()
                            matched_text = replaced_text[start:end]
                            # Заменяем ТОЛЬКО если найденный текст полностью заглавными буквами
                            # Это означает, что это плейсхолдер во втором столбце, а не название параметра
                            if matched_text.isupper():
                                replaced_text = replaced_text[:start] + new_text + replaced_text[end:]
                                needs_replace = True
                    
                    if needs_replace:
                        if paragraph.runs:
                            first_run = paragraph.runs[0]
                            for run in paragraph.runs:
                                run.text = ''
                            first_run.text = replaced_text
                        else:
                            paragraph.add_run(replaced_text)
                
                # Замена в параграфах
                for paragraph in doc.paragraphs:
                    replace_in_paragraph(paragraph)
                
                # Замена в таблицах
                for table in doc.tables:
                    for row in table.rows:
                        for cell in row.cells:
                            for paragraph in cell.paragraphs:
                                replace_in_paragraph(paragraph)
                
                doc.save(modified_docx_path)
                
            except Exception as e:
                # Если python-docx не работает, используем zipfile метод
                print(f"⚠️ Ошибка при использовании python-docx: {str(e)}")
                import zipfile
                import xml.etree.ElementTree as ET
                import shutil
                
                temp_docx_path = os.path.join(temp_dir, 'temp_docx.docx')
                
                file_contents = {}
                with zipfile.ZipFile(tp_docx_path, 'r') as source_docx:
                    for item in source_docx.infolist():
                        file_contents[item.filename] = source_docx.read(item.filename)
                
                if 'word/document.xml' in file_contents:
                    xml_content = file_contents['word/document.xml']
                    try:
                        xml_str = xml_content.decode('utf-8') if isinstance(xml_content, bytes) else xml_content
                        root = ET.fromstring(xml_str)
                        
                        sorted_replacements = sorted(replacements.items(), key=lambda x: len(x[0]), reverse=True)
                        
                        def replace_text_in_xml(elem):
                            import re
                            if elem.text:
                                # Заменяем только полностью заглавные слова (плейсхолдеры)
                                for old_text, new_text in sorted_replacements:
                                    # Ищем все вхождения и заменяем только заглавные
                                    pattern = re.escape(old_text)
                                    matches = list(re.finditer(pattern, elem.text, re.IGNORECASE))
                                    for match in reversed(matches):
                                        start, end = match.span()
                                        matched = elem.text[start:end]
                                        if matched.isupper():
                                            elem.text = elem.text[:start] + new_text + elem.text[end:]
                            if elem.tail:
                                # Аналогично для tail
                                for old_text, new_text in sorted_replacements:
                                    pattern = re.escape(old_text)
                                    matches = list(re.finditer(pattern, elem.tail, re.IGNORECASE))
                                    for match in reversed(matches):
                                        start, end = match.span()
                                        matched = elem.tail[start:end]
                                        if matched.isupper():
                                            elem.tail = elem.tail[:start] + new_text + elem.tail[end:]
                            for child in elem:
                                replace_text_in_xml(child)
                        
                        replace_text_in_xml(root)
                        xml_bytes = ET.tostring(root, encoding='utf-8', xml_declaration=True)
                        file_contents['word/document.xml'] = xml_bytes
                    except Exception as xml_error:
                        print(f"⚠️ Ошибка обработки XML: {xml_error}")
                        xml_str = xml_content.decode('utf-8') if isinstance(xml_content, bytes) else xml_content
                        # Простая замена только полностью заглавных слов (плейсхолдеров)
                        import re
                        for old_text, new_text in sorted_replacements:
                            # Ищем все вхождения и заменяем только заглавные
                            pattern = re.escape(old_text)
                            matches = list(re.finditer(pattern, xml_str, re.IGNORECASE))
                            for match in reversed(matches):
                                start, end = match.span()
                                matched = xml_str[start:end]
                                if matched.isupper():
                                    xml_str = xml_str[:start] + new_text + xml_str[end:]
                        file_contents['word/document.xml'] = xml_str.encode('utf-8')
                
                with zipfile.ZipFile(temp_docx_path, 'w', zipfile.ZIP_DEFLATED) as new_docx:
                    for filename, content in file_contents.items():
                        new_docx.writestr(filename, content)
                
                shutil.move(temp_docx_path, modified_docx_path)
            
            # Конвертируем DOCX в PDF
            tp_pdf_path = os.path.join(temp_dir, 'ТП_modified.pdf')
            
            # Пробуем использовать MS Word или LibreOffice для конвертации (аналогично КП.docx)
            pdf_converted = False
            try:
                import sys
                if sys.platform == 'win32':
                    try:
                        import win32com.client
                        import pythoncom
                        
                        pythoncom.CoInitialize()
                        word = None
                        try:
                            word = win32com.client.Dispatch("Word.Application")
                            word.Visible = False
                            word.DisplayAlerts = 0
                            
                            doc_path = os.path.abspath(modified_docx_path).replace('/', '\\')
                            doc = word.Documents.Open(doc_path, ReadOnly=True, ConfirmConversions=False, AddToRecentFiles=False)
                            
                            pdf_path = os.path.abspath(tp_pdf_path).replace('/', '\\')
                            doc.SaveAs2(FileName=pdf_path, FileFormat=17)
                            
                            # Закрываем документ ПЕРЕД выходом из Word
                            doc.Close(False)
                            
                            # Принудительно освобождаем объекты COM
                            del doc
                            
                            # Закрываем Word
                            word.Quit(SaveChanges=False)
                            word = None
                            
                            # Даем время Word полностью закрыться
                            import time
                            time.sleep(1.0)
                            
                            # Ждем, пока Word полностью освободит файл
                            max_wait = 8  # Максимальное время ожидания в секундах
                            wait_interval = 0.2
                            waited = 0
                            while waited < max_wait:
                                time.sleep(wait_interval)
                                waited += wait_interval
                                # Пробуем открыть файл для чтения, чтобы проверить, не занят ли он
                                try:
                                    if os.path.exists(tp_pdf_path):
                                        file_size = os.path.getsize(tp_pdf_path)
                                        if file_size > 0:
                                            # Пробуем открыть файл для чтения
                                            with open(tp_pdf_path, 'rb') as test_file:
                                                test_file.read(1)
                                            # Файл доступен для чтения
                                            pdf_converted = True
                                            print(f"✅ PDF создан через MS Word для ТП.docx ({file_size} байт)")
                                            break
                                except (PermissionError, IOError, OSError) as file_err:
                                    # Файл еще занят, продолжаем ждать
                                    if waited >= max_wait - wait_interval:
                                        print(f"⚠️ Файл все еще занят после {max_wait} секунд ожидания: {str(file_err)}")
                                    continue
                        finally:
                            if word:
                                try:
                                    word.Quit(SaveChanges=False)
                                except:
                                    pass
                            try:
                                pythoncom.CoUninitialize()
                            except:
                                pass
                    except:
                        pass
                
                if not pdf_converted:
                    try:
                        from docx2pdf import convert
                        print("🔄 Пробую использовать docx2pdf для ТП.docx...")
                        convert(modified_docx_path, tp_pdf_path)
                        if os.path.exists(tp_pdf_path) and os.path.getsize(tp_pdf_path) > 0:
                            pdf_converted = True
                            print("✅ PDF создан через docx2pdf для ТП.docx")
                    except Exception as e:
                        print(f"⚠️ Ошибка docx2pdf для ТП.docx: {str(e)}")
            except Exception as e:
                print(f"⚠️ Ошибка при конвертации ТП.docx: {str(e)}")
                import traceback
                traceback.print_exc()
            
            if not pdf_converted:
                error_msg = "Не удалось конвертировать ТП.docx в PDF. "
                error_msg += "Убедитесь, что установлен LibreOffice или Microsoft Word."
                print(f"❌ {error_msg}")
                return jsonify({"error": error_msg}), 500
            
            # Проверяем, что файл существует и не пустой
            # Дополнительная проверка доступности файла перед возвратом
            import time
            if pdf_converted:
                # Файл уже был проверен в цикле ожидания, но делаем финальную проверку
                time.sleep(0.3)
                
                # Пробуем открыть файл несколько раз, если он занят
                max_retries = 15
                retry_count = 0
                file_ready = False
                
                while retry_count < max_retries:
                    try:
                        if os.path.exists(tp_pdf_path):
                            file_size = os.path.getsize(tp_pdf_path)
                            if file_size > 0:
                                # Пробуем открыть файл для чтения
                                with open(tp_pdf_path, 'rb') as test_file:
                                    test_file.read(1)
                                file_ready = True
                                break
                    except (PermissionError, IOError, OSError) as e:
                        if retry_count < max_retries - 1:
                            print(f"⚠️ Файл еще занят (попытка {retry_count + 1}/{max_retries}): {str(e)}")
                            retry_count += 1
                            time.sleep(0.3)
                        else:
                            print(f"❌ Не удалось получить доступ к файлу после {max_retries} попыток")
                            return jsonify({"error": "Не удалось получить доступ к PDF файлу (файл занят другим процессом). Попробуйте закрыть Microsoft Word и повторить попытку."}), 500
            
            if not os.path.exists(tp_pdf_path):
                return jsonify({"error": "PDF файл не был создан"}), 500
            
            if os.path.getsize(tp_pdf_path) == 0:
                return jsonify({"error": "Созданный PDF файл пустой"}), 500
            
            print(f"✅ ТП.docx успешно конвертирован в PDF ({os.path.getsize(tp_pdf_path)} байт)")
            
            # Читаем PDF файл в память (аналогично КП.docx) для избежания проблем с блокировкой
            try:
                with open(tp_pdf_path, 'rb') as pdf_file:
                    pdf_data = pdf_file.read()
                
                # Создаем BytesIO объект из данных
                pdf_buffer = BytesIO(pdf_data)
                pdf_buffer.seek(0)
                
                # Возвращаем PDF из памяти
                return send_file(
                    pdf_buffer,
                    mimetype='application/pdf',
                    as_attachment=False,
                    download_name='technical_specs.pdf'
                )
            except (PermissionError, IOError, OSError) as read_error:
                print(f"❌ Ошибка при чтении PDF файла: {str(read_error)}")
                return jsonify({"error": f"Не удалось прочитать PDF файл: {str(read_error)}"}), 500
            
    except Exception as e:
        print(f"❌ Ошибка при генерации ТП: {str(e)}")
        import traceback
        traceback.print_exc()
        error_details = str(e)
        return jsonify({"error": f"Ошибка при генерации ТП: {error_details}"}), 500


@app.route('/api/telegram/send', methods=['POST'])
def send_telegram_message():
    """
    Отправка сообщения в Telegram
    POST /api/telegram/send
    Body: {
        "message": "Текст сообщения",
        "formData": {
            "name": "...",
            "email": "...",
            ...
        }
    }
    """
    try:
        # Получаем токен и chat_id из переменных окружения
        bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
        chat_id = os.environ.get('TELEGRAM_CHAT_ID')
        
        if not bot_token or not chat_id:
            return jsonify({
                "success": False,
                "error": "Telegram bot не настроен на сервере"
            }), 500
        
        data = request.get_json()
        
        if not data or 'message' not in data:
            return jsonify({
                "success": False,
                "error": "Сообщение не указано"
            }), 400
        
        message = data.get('message')
        
        # Отправляем сообщение в Telegram
        telegram_api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        
        response = requests.post(
            telegram_api_url,
            json={
                'chat_id': chat_id,
                'text': message,
                'parse_mode': 'HTML'
            },
            timeout=10
        )
        
        response_data = response.json()
        
        if response_data.get('ok'):
            print(f"✅ Сообщение отправлено в Telegram (chat_id: {chat_id})")
            return jsonify({
                "success": True,
                "message": "Сообщение успешно отправлено"
            }), 200
        else:
            error_message = response_data.get('description', 'Неизвестная ошибка')
            print(f"❌ Ошибка отправки в Telegram: {error_message}")
            return jsonify({
                "success": False,
                "error": error_message
            }), 500
            
    except requests.exceptions.RequestException as e:
        print(f"❌ Ошибка запроса к Telegram API: {str(e)}")
        return jsonify({
            "success": False,
            "error": f"Ошибка подключения к Telegram: {str(e)}"
        }), 500
    except Exception as e:
        print(f"❌ Неожиданная ошибка: {str(e)}")
        return jsonify({
            "success": False,
            "error": "Внутренняя ошибка сервера"
        }), 500


# ============= ОБРАБОТЧИКИ ОШИБОК =============

@app.errorhandler(404)
def not_found(error):
    """Обработка 404 ошибки"""
    return jsonify({"error": "Страница не найдена"}), 404

@app.errorhandler(500)
def internal_error(error):
    """Обработка 500 ошибки"""
    return jsonify({"error": "Внутренняя ошибка сервера"}), 500


# ============= СТАТИЧЕСКИЕ ФАЙЛЫ =============

@app.route('/<path:path>')
def serve_static(path):
    """Отдача статических файлов (изображения, JSON и т.д.)"""
    return send_from_directory('.', path)


# ============= ЗАПУСК СЕРВЕРА =============

def get_local_ip():
    """Получение локального IP-адреса"""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"


if __name__ == '__main__':
    print("\n" + "="*60)
    print("🚀 Запуск AGM Backend Server")
    print("="*60)
    
    if PUMP_DATA:
        pump_count = len(PUMP_DATA.get('pumpParabolas', []))
        print(f"✅ Загружено насосов: {pump_count}")
        print(f"✅ Загружено вариантов: {len(PUMP_DATA.get('pumpVariants', []))}")
        print(f"✅ Загружено двигателей: {len(PUMP_DATA.get('motors', []))}")
    else:
        print("⚠️  Данные о насосах НЕ загружены!")
    
    local_ip = get_local_ip()
    
    print("\n📡 Доступ к серверу:")
    print(f"   🏠 Локально:      http://localhost:5000/")
    print(f"   🌐 В локальной сети: http://{local_ip}:5000/")
    
    print("\n📋 Основные страницы:")
    print("   🌐 /select.html   - Подбор насоса")
    print("   🌐 /calc.html     - Расчёт трубопровода")
    print("   🌐 /result.html   - Результаты")
    print("   🌐 /login.html    - Вход/Регистрация")
    print("   🌐 /saved.html    - Сохраненные результаты")
    
    print("\n📋 API Endpoints:")
    print("   📊 GET  /api/health                    - Проверка работы")
    print("   📊 GET  /api/pumps                     - Все насосы")
    print("   📊 POST /api/pumps/filter              - Фильтр насосов")
    print("   📊 GET  /api/pump/<name>               - Насос по имени")
    print("   📊 POST /api/calculate                 - Расчёт насоса")
    print("   📊 GET  /api/motors                    - Список двигателей")
    print("   📊 POST /api/telegram/send             - Отправка в Telegram")
    print("   📄 POST /api/generate-tkp              - Генерация ТКП")
    
    print("\n🔐 API Авторизации:")
    print("   👤 POST /api/auth/register             - Регистрация")
    print("   👤 POST /api/auth/login                - Вход")
    print("   👤 POST /api/auth/logout               - Выход")
    print("   👤 GET  /api/auth/user                 - Текущий пользователь")
    
    print("\n💾 API Сохраненных результатов:")
    print("   💾 POST   /api/results/save            - Сохранить результат")
    print("   💾 GET    /api/results                 - Все результаты")
    print("   💾 GET    /api/results/<id>            - Результат по ID")
    print("   💾 DELETE /api/results/<id>            - Удалить результат")
    
    print("\n" + "="*60)
    print("💡 Для остановки сервера нажмите Ctrl+C")
    print("💡 Для доступа из локальной сети см. LOCAL_NETWORK.md")
    print("="*60 + "\n")
    
    # Запускаем сервер
    # В production используем переменную PORT (для облачных платформ)
    port = int(os.environ.get('PORT', 5000))
    debug_mode = os.environ.get('FLASK_ENV') != 'production'
    
    app.run(
        host='0.0.0.0',  # Доступен из локальной сети
        port=port,        # Порт из переменной окружения или 5000 по умолчанию
        debug=debug_mode # Режим отладки только в development
    )


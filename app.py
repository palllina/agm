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

                              
load_dotenv()

# PDF для насосов КН: True — первая страница из реклама.pdf, False — текстовая страница как раньше
KN_USE_ADVERTISEMENT_PAGE = True
KN_ADVERTISEMENT_PDF = 'реклама.pdf'

# Привязка диаметра двигателя (da) к насосу — data1.json, ключ "motorModelDa"
# Ключ: полное название, фрагмент ("3231.180 СН 6") или код модели ("3231")

app = Flask(__name__, 

            static_folder='.',

            template_folder='.')


app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'                                                        

database_url = os.environ.get('DATABASE_URL')

if database_url:

    if database_url.startswith('postgres://'):

        database_url = database_url.replace('postgres://', 'postgresql://', 1)

    app.config['SQLALCHEMY_DATABASE_URI'] = database_url

else:
                             

    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///agm.db'


app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)
db.init_app(app)

CORS(app, supports_credentials=True)
login_manager = LoginManager()

login_manager.init_app(app)

login_manager.login_view = 'login_page'

@login_manager.unauthorized_handler

def unauthorized():

    """Для запросов к /api/* возвращаем 401 JSON, иначе редирект на вход."""

    if request.path.startswith('/api/'):

        return jsonify({"error": "Требуется авторизация", "authenticated": False}), 401

    return redirect(url_for('login_page'))



@login_manager.user_loader

def load_user(user_id):

    """Загрузка пользователя для Flask-Login"""

    return User.query.get(int(user_id))


with app.app_context():

    db.create_all()

                                                             

    polina_user = User.query.filter_by(username='polina').first()

    if not polina_user:

        polina = User(

            username='polina',

            email='-',

            is_admin=True

        )

        polina.set_password('123')

        db.session.add(polina)

        db.session.commit()

        print("✅ Пользователь 'polina' создан автоматически (пароль: 123)")


def get_client_ip():

    """Получение реального IP-адреса клиента"""

    x_forwarded_for = request.headers.get('X-Forwarded-For')

    if x_forwarded_for:

        ip = x_forwarded_for.split(',')[0].strip()

        if ip and ip != 'unknown':

            return ip

    
    x_real_ip = request.headers.get('X-Real-IP')

    if x_real_ip:

        ip = x_real_ip.strip()

        if ip and ip != 'unknown':

            return ip

    
    cf_ip = request.headers.get('CF-Connecting-IP')

    if cf_ip:

        ip = cf_ip.strip()

        if ip and ip != 'unknown':

            return ip

                                       

    remote_addr = request.remote_addr

    if remote_addr and remote_addr != 'unknown':

        return remote_addr

                                                   

    if request.environ.get('HTTP_X_FORWARDED_FOR'):

        ip = request.environ.get('HTTP_X_FORWARDED_FOR').split(',')[0].strip()

        if ip and ip != 'unknown':

            return ip

    

    return 'Unknown'

                                       

def load_pump_data():

    """Загружает данные о насосах из data1.json"""

    try:

        with open('data1.json', 'r', encoding='utf-8') as f:

            return json.load(f)

    except FileNotFoundError:

        print("⚠️  Файл data1.json не найден!")

        return None

    except json.JSONDecodeError as e:

        print(f"⚠️  Ошибка парсинга JSON: {e}")

        return None
                        

PUMP_DATA = load_pump_data()


def _html_with_embedded_data(filename):

    """Читает HTML-файл и вставляет данные насосов в <head> (без отдельного запроса data1.json в Network)."""

    extra_scripts = ''
    if filename == 'result.html':
        pdf_settings = json.dumps({
            'knUseAdPage': KN_USE_ADVERTISEMENT_PAGE,
            'knAdPdfUrl': f'/{KN_ADVERTISEMENT_PDF}',
        }, ensure_ascii=False)
        extra_scripts = f'<script>window.__PDF_SETTINGS__={pdf_settings};</script>'

    if PUMP_DATA is None:

        if extra_scripts:
            try:
                path = os.path.join(os.path.dirname(__file__), filename)
                with open(path, 'r', encoding='utf-8') as f:
                    html = f.read()
                if '</head>' in html:
                    html = html.replace('</head>', extra_scripts + '\n</head>', 1)
                else:
                    html = extra_scripts + '\n' + html
                from flask import Response
                return Response(html, mimetype='text/html; charset=utf-8')
            except Exception:
                pass
        return send_from_directory('.', filename)

    try:

        path = os.path.join(os.path.dirname(__file__), filename)

        with open(path, 'r', encoding='utf-8') as f:

            html = f.read()

    except Exception:

        return send_from_directory('.', filename)
                                                                                                      

    import base64

    pump_data = load_pump_data() or PUMP_DATA
    if pump_data is None:
        return send_from_directory('.', filename)

    json_str = json.dumps(pump_data, ensure_ascii=True)

    data_b64 = base64.b64encode(json_str.encode('utf-8')).decode('ascii')

    script = f'<script>window.__PUMP_DATA__=JSON.parse(atob("{data_b64}"));</script>'
    script += '\n' + extra_scripts if extra_scripts else ''

    if '</head>' in html:

        html = html.replace('</head>', script + '\n</head>', 1)

    else:

        html = script + '\n' + html

    from flask import Response

    return Response(html, mimetype='text/html; charset=utf-8')

@app.route('/')

def index():

    """Главная страница - подбор насоса (данные встроены в страницу)"""

    return _html_with_embedded_data('select.html')


@app.route('/select.html')

def select_page():

    """Страница подбора насоса (данные встроены в страницу)"""

    return _html_with_embedded_data('select.html')


@app.route('/calc.html')

def calc_page():

    """Страница расчёта трубопровода"""

    return send_from_directory('.', 'calc.html')


@app.route('/result.html')

def result_page():

    """Страница результатов (данные встроены в страницу)"""

    return _html_with_embedded_data('result.html')


@app.route('/login.html')

def login_page():

    """Страница входа/регистрации"""

    return send_from_directory('.', 'login.html')

@app.route('/saved.html')

@login_required

def saved_page():

    """Страница сохраненных результатов (требует авторизации)"""

    return send_from_directory('.', 'saved.html')


@app.route('/api/pumps', methods=['GET'])
def get_all_pumps():
    # Читаем файл прямо во время запроса пользователя
    current_data = load_pump_data() 
    if current_data is None:
        return jsonify({"error": "Данные о насосах не загружены"}), 500
    
    return jsonify(current_data), 200



@app.route('/api/pumps/filter', methods=['POST'])

def filter_pumps():

    """
    Фильтрация насосов по параметрам
    POST /api/pumps/filter
    Body: {
        "flow": 100,
        "head": 10,
        "pumpType": "sewage",
        "density": 1000
    }
    """

    if PUMP_DATA is None:

        return jsonify({"error": "Данные о насосах не загружены"}), 500

    
    data = request.get_json()

    
    flow = data.get('flow')

    head = data.get('head')

    pump_type = data.get('pumpType', 'sewage')

    density = data.get('density', 1000)

    
    if flow is None or head is None:

        return jsonify({"error": "Необходимо указать flow и head"}), 400

    
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

        pump_name = pump_name.replace('_', ' ')
   

    for pump in PUMP_DATA.get('pumpParabolas', []):

        if pump.get('name') == pump_name:

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

    
    print(f"Расчёт насоса: подача={data.get('flow')}, напор={data.get('head')}")
    

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

                                                   

    cat_ips = ['192.168.88.180', '192.168.88.105', '192.168.88.162', '192.168.88.137']

    show_cats = client_ip in cat_ips

    

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
        "email": "-"
    }
    
    """

    try:

         
        existing_users = User.query.all()

        if existing_users:

            return jsonify({

                "success": False,

                "error": "Пользователи уже существуют. Используйте /api/auth/login для входа."

            }), 403

                                

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

        
        username = data.get('username', 'polina').strip()

        password = data.get('password', '123')

        email = data.get('email', f'{username}@agm.local').strip()


        if not username or not password:

            return jsonify({

                "success": False,

                "error": "Имя пользователя и пароль обязательны"

            }), 400

                                                         

        existing_user = User.query.filter_by(username=username).first()

        if existing_user:

            return jsonify({

                "success": False,

                "error": f"Пользователь '{username}' уже существует"

            }), 400

        
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

        
        user = User.query.filter_by(username=username).first()


        if not user or not user.check_password(password):

            return jsonify({"success": False, "error": "Неверное имя пользователя или пароль"}), 401
  

        login_user(user, remember=True)

        session.permanent = True

        

        print(f"✅ Пользователь вошел: {username}")

        return jsonify({

            "success": True,

            "message": "Вход выполнен успешно",

            "user": user.to_dict()

        }), 200
       

    except Exception as e:

        print(f"Ошибка входа: {str(e)}")

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

    print(f"Пользователь вышел: {username}")

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

        if current_user.is_admin:

            results = SavedResult.query.order_by(SavedResult.created_at.desc()).all()

            print(f"👑 Администратор {current_user.username} получает ВСЕ результаты")

        else:

            results = SavedResult.query.filter_by(user_id=current_user.id).order_by(SavedResult.created_at.desc()).all()

                                                    

        results_data = []

        for result in results:

            result_dict = result.to_dict()

                                    

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
    Генерация технико-коммерческого предложения. Только для администраторов.
    POST /api/generate-tkp
    Требуется авторизация и права администратора
    FormData: {
        "tech_pdf": File (PDF технического описания),
        "customer": "Название заказчика",
        "pump_name": "Название насоса",
        "price": "100" (цена насоса)
    }
    """

    if not current_user.is_admin:

        return jsonify({"error": "Доступ только для администраторов"}), 403

    try:

                                              

        if 'tech_pdf' not in request.files:

            return jsonify({"error": "Не указан PDF технического описания"}), 400

        

        customer = request.form.get('customer', '').strip()

        pump_name = request.form.get('pump_name', '').strip()

        price_str = request.form.get('price', '100').strip()

        pump_type = request.form.get('pump_type', '').strip()                                                    

        

        if not customer:

            return jsonify({"error": "Не указан заказчик"}), 400

        
        try:

            price = float(price_str)

        except ValueError:

            price = 100.0

                                               

        tax_amount = price * 0.22

        total_price = price + tax_amount

                              

        today_date = datetime.now().strftime('%d.%m.%Y')

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

            next_number = current_number + 1

               

            with open(counter_file, 'w', encoding='utf-8') as f:

                f.write(str(next_number))

                                                       

            return f'{next_number:06d}'

        
        tkp_number = get_next_tkp_number()

                                     

        kp_docx_path = os.path.join(os.path.dirname(__file__), 'КП.docx')

        if not os.path.exists(kp_docx_path):

            return jsonify({"error": "Файл КП.docx не найден"}), 404

                            

        with tempfile.TemporaryDirectory() as temp_dir:

            tech_pdf_file = request.files['tech_pdf']

            tech_pdf_path = os.path.join(temp_dir, 'tech.pdf')

            tech_pdf_file.save(tech_pdf_path)

            
            modified_docx_path = os.path.join(temp_dir, 'КП_modified.docx')

            replacements = {

                'ЦЕНА + 22%': f'{total_price:.2f}',

                'ЦЕНА +22%': f'{total_price:.2f}',

                'ЦЕНА+ 22%': f'{total_price:.2f}',

                'ЦЕНА+22%': f'{total_price:.2f}',

                f'{price:.2f} + 22%': f'{total_price:.2f}',                            

                f'{price:.2f} +22%': f'{total_price:.2f}',

                f'{price:.2f}+ 22%': f'{total_price:.2f}',

                f'{price:.2f}+22%': f'{total_price:.2f}',

                '22% ОТ ЦЕНЫ': f'{tax_amount:.2f}',

                '22% от цены': f'{tax_amount:.2f}',

                f'22% от {price:.2f}': f'{tax_amount:.2f}',

                'НОМЕР': tkp_number,                        

                'ДАТА': today_date,

                'ЗАКАЗЧИК': customer,

                'НАЗВАНИЕ': pump_name,

                'ЦЕНА': f'{price:.2f}',

                'ТИП': pump_type if pump_type else ''                                                    

            }

                                                                   

            try:

                from docx import Document

                              

                doc = Document(kp_docx_path)

                                                

                def replace_in_paragraph(paragraph):

                                                                 

                    full_text = paragraph.text

                    if not full_text:

                        return

                    
                    needs_replace = False

                    replaced_text = full_text

                                                                                   

                    sorted_replacements = sorted(replacements.items(), key=lambda x: len(x[0]), reverse=True)

                    

                    for old_text, new_text in sorted_replacements:

                        if old_text in replaced_text:

                            needs_replace = True

                            replaced_text = replaced_text.replace(old_text, new_text)

                    

                    if needs_replace:

                                                     

                        if paragraph.runs:

                            first_run = paragraph.runs[0]

                                              

                            for run in paragraph.runs:

                                run.text = ''

                                                                

                            first_run.text = replaced_text

                        else:

                                                          

                            paragraph.add_run(replaced_text)

                                

                for paragraph in doc.paragraphs:

                    replace_in_paragraph(paragraph)

                               

                for table in doc.tables:

                    for row in table.rows:

                        for cell in row.cells:

                            for paragraph in cell.paragraphs:

                                replace_in_paragraph(paragraph)

                                             

                doc.save(modified_docx_path)

                print(f"✅ DOCX документ сохранен: {modified_docx_path}")

                                                    

                if not os.path.exists(modified_docx_path):

                    raise FileNotFoundError(f"Файл не был создан: {modified_docx_path}")

                if os.path.getsize(modified_docx_path) == 0:

                    raise ValueError(f"Файл пустой: {modified_docx_path}")

                

            except Exception as e:
                                             

                print(f"⚠️ Ошибка при использовании python-docx: {str(e)}")

                import traceback

                traceback.print_exc()
                                                                                                 

                import zipfile

                import xml.etree.ElementTree as ET

                import shutil

                                                  

                temp_docx_path = os.path.join(temp_dir, 'temp_docx.docx')

                                                      

                file_contents = {}

                with zipfile.ZipFile(kp_docx_path, 'r') as source_docx:

                    for item in source_docx.infolist():

                        file_contents[item.filename] = source_docx.read(item.filename)

                                                          

                if 'word/document.xml' in file_contents:

                    xml_content = file_contents['word/document.xml']

                    try:
                                              

                        if isinstance(xml_content, bytes):

                            xml_str = xml_content.decode('utf-8')

                        else:

                            xml_str = xml_content

                               

                        root = ET.fromstring(xml_str)

                                        

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

                                                   

                        xml_bytes = ET.tostring(root, encoding='utf-8', xml_declaration=True)

                        file_contents['word/document.xml'] = xml_bytes

                    except Exception as xml_error:

                        print(f"⚠️ Ошибка обработки XML: {xml_error}")

                                                                                  

                        xml_str = xml_content.decode('utf-8') if isinstance(xml_content, bytes) else xml_content

                        sorted_replacements = sorted(replacements.items(), key=lambda x: len(x[0]), reverse=True)

                        for old_text, new_text in sorted_replacements:

                            xml_str = xml_str.replace(old_text, new_text)

                        file_contents['word/document.xml'] = xml_str.encode('utf-8')

                            

                with zipfile.ZipFile(temp_docx_path, 'w', zipfile.ZIP_DEFLATED) as new_docx:

                    for filename, content in file_contents.items():

                        new_docx.writestr(filename, content)
                                

                shutil.move(temp_docx_path, modified_docx_path)

                print(f"✅ DOCX документ сохранен через zipfile: {modified_docx_path}")

                                                                     

            if not os.path.exists(modified_docx_path):

                return jsonify({"error": f"Не удалось создать DOCX файл: {modified_docx_path}"}), 500

            

            if os.path.getsize(modified_docx_path) == 0:

                return jsonify({"error": f"Созданный DOCX файл пустой: {modified_docx_path}"}), 500

            

            print(f"✅ DOCX файл готов для конвертации: {modified_docx_path} ({os.path.getsize(modified_docx_path)} байт)")
                                     

            kp_pdf_path = os.path.join(temp_dir, 'КП_modified.pdf')

            
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

                    if result.returncode == 0:

                                                                   

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

                
                try:

                    import sys

                    if sys.platform == 'win32':

                        try:

                            import win32com.client

                            import pythoncom

                            

                            print("🔄 Пробую использовать MS Word через COM...")

                                                                                    

                            pythoncom.CoInitialize()

                                    

                            word = None

                            try:

                                word = win32com.client.Dispatch("Word.Application")

                                word.Visible = False

                                word.DisplayAlerts = 0                            

                                
                                doc_path = os.path.abspath(modified_docx_path).replace('/', '\\')

                                print(f"📄 Открываю документ: {doc_path}")

                                

                                if not os.path.exists(doc_path):

                                    raise FileNotFoundError(f"Файл не найден: {doc_path}")

                                                                              

                                try:

                                    doc = word.Documents.Open(

                                        FileName=doc_path,

                                        ReadOnly=True,

                                        ConfirmConversions=False,

                                        AddToRecentFiles=False

                                    )

                                except Exception as open_err:

                                                                                     

                                    print(f"⚠️ Не удалось открыть с ReadOnly, пробую без ReadOnly...")

                                    doc = word.Documents.Open(

                                        FileName=doc_path,

                                        ConfirmConversions=False,

                                        AddToRecentFiles=False

                                    )

                                              

                                pdf_path = os.path.abspath(kp_pdf_path).replace('/', '\\')

                                print(f"💾 Сохраняю PDF: {pdf_path}")
                                 

                                pdf_dir = os.path.dirname(pdf_path)

                                if not os.path.exists(pdf_dir):

                                    os.makedirs(pdf_dir, exist_ok=True)

                                

                                doc.SaveAs2(

                                    FileName=pdf_path,

                                    FileFormat=17                    

                                )

                                
                                doc.Close(False)                                  

                                word.Quit(SaveChanges=False)

                                word = None
                                              

                                import time

                                time.sleep(0.5)
                    

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

            
            try:

                from PyPDF2 import PdfReader, PdfWriter
              

                writer = PdfWriter()

                                                                            

                if os.path.exists(kp_pdf_path):

                    with open(kp_pdf_path, 'rb') as kp_pdf:

                        kp_reader = PdfReader(kp_pdf)

                        for page in kp_reader.pages:

                            writer.add_page(page)

                
                                            

                with open(tech_pdf_path, 'rb') as tech_pdf:

                    tech_reader = PdfReader(tech_pdf)

                    for page in tech_reader.pages:

                        writer.add_page(page)

                
                                 

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

                                           

                try:

                    from pypdf import PdfReader, PdfWriter

                    

                    writer = PdfWriter()

                                                                                                          

                    if os.path.exists(kp_pdf_path):

                        with open(kp_pdf_path, 'rb') as kp_pdf:

                            kp_reader = PdfReader(kp_pdf)

                            for page in kp_reader.pages:

                                writer.add_page(page)

                    
                    with open(tech_pdf_path, 'rb') as tech_pdf:

                        tech_reader = PdfReader(tech_pdf)

                        for page in tech_reader.pages:

                            writer.add_page(page)

                                                     

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

                               

        drawings_dir = os.path.join(os.path.dirname(__file__), 'Установы')

        

        if not os.path.exists(drawings_dir):

            return jsonify({"found": False}), 200

                                       

        pdf_files = [f for f in os.listdir(drawings_dir) if f.lower().endswith('.pdf')]

        

        if not pdf_files:

            return jsonify({"found": False}), 200

                                                                         

        def normalize_pump_name(name):

               
            normalized = name.replace(' В ', ' ').replace('В ', '').strip()

            import re

            normalized = re.sub(r'\.\d+', '', normalized)

            normalized = re.sub(r'\s+\d+(\s+\d+)*$', '', normalized).strip()

            normalized = ' '.join(normalized.split())

            return normalized
                         

        normalized_pump_name = normalize_pump_name(pump_name)

        matching_files = []

        

        for pdf_file in pdf_files:

                                     

            file_name_without_ext = pdf_file[:-4]                  

                                                                

            normalized_file_name = ' '.join(file_name_without_ext.split())

                                                                                                  

            if normalized_file_name in normalized_pump_name:

                matching_files.append((pdf_file, len(normalized_file_name)))

        

        if not matching_files:

            return jsonify({"found": False}), 200

        
                                                         

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

                                                                                   

        if not all(c.isalnum() or c in (' ', '-', '.', '_') for c in filename):

            return jsonify({"error": "Некорректное имя файла"}), 400

                

        file_path = os.path.join(os.path.dirname(__file__), 'Установы', filename)

        

        if not os.path.exists(file_path):

            return jsonify({"error": "Файл не найден"}), 404

        
        if not filename.lower().endswith('.pdf'):

            return jsonify({"error": "Файл не является PDF"}), 400
                               

        try:

            from pypdf import PdfReader, PdfWriter

        except ImportError:

            try:

                from PyPDF2 import PdfReader, PdfWriter

            except ImportError:

                                                           

                return send_file(

                    file_path,

                    mimetype='application/pdf',

                    as_attachment=False

                )

                                 

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
    Генерация страницы технических характеристик из ТП.docx. Доступно всем авторизованным.
    POST /api/generate-tp
    Body: {
        "specData": "JSON строка с данными из таблицы характеристик"
    }
    """

    try:

        data = request.get_json()

        if not data or 'specData' not in data:

            return jsonify({"error": "Не указаны данные характеристик"}), 400

                                

        import json

        spec_data = json.loads(data.get('specData', '{}'))

        
        tp_docx_path = os.path.join(os.path.dirname(__file__), 'ТП.docx')

        if not os.path.exists(tp_docx_path):

            return jsonify({"error": "Файл ТП.docx не найден"}), 404

                           

        with tempfile.TemporaryDirectory() as temp_dir:

            modified_docx_path = os.path.join(temp_dir, 'ТП_modified.docx')

            
                                                    

            replacements = {}

                                                                                                                  

            if 'НАЗВАНИЕ' in spec_data:

                replacements['НАЗВАНИЕ'] = str(spec_data['НАЗВАНИЕ'])

            

            for param, value in spec_data.items():

                                                                         

                if 'КПД' in param.upper() or 'ЭФФЕКТИВНОСТЬ' in param.upper():

                    continue                                                          

                
                                                             

                if 'НАЗВАНИЕ' in param.upper():

                    continue
                                             

                param_upper = param.upper()

                replacements[param_upper] = str(value)

                                                

                if ' (оптимальная)' in param:

                    param_clean = param.replace(' (оптимальная)', '').upper()

                    replacements[param_clean + ' (ОПТИМАЛЬНАЯ)'] = str(value)

                    replacements[param_clean + ' (ОПТИМАЛЬНАЯ ТОЧКА)'] = str(value)

            
                                                                 

            if 'ЭФФ1' in spec_data:

                replacements['ЭФФ1'] = str(spec_data['ЭФФ1'])

                replacements['КПД (РАБОЧАЯ)'] = str(spec_data['ЭФФ1'])

                replacements['КПД РАБОЧАЯ'] = str(spec_data['ЭФФ1'])

            if 'ЭФФ2' in spec_data:

                replacements['ЭФФ2'] = str(spec_data['ЭФФ2'])

                replacements['КПД (ОПТИМАЛЬНАЯ)'] = str(spec_data['ЭФФ2'])

                replacements['КПД ОПТИМАЛЬНАЯ'] = str(spec_data['ЭФФ2'])

            

            if 'Диаметр' in spec_data:

                replacements['ДИАМЕТР'] = str(spec_data['Диаметр'])

            if 'Диаметр рабочего колеса' in spec_data:

                replacements['ДИАМЕТР РАБОЧЕГО КОЛЕСА'] = str(spec_data['Диаметр рабочего колеса'])

            


            if 'Масса' in spec_data:

                replacements['МАССА'] = str(spec_data['Масса'])

                                          

            if 'ДЛИНА' in spec_data:

                replacements['ДЛИНА'] = str(spec_data['ДЛИНА'])

            if 'Длина' in spec_data:

                replacements['ДЛИНА'] = str(spec_data['Длина'])

            if 'Длина кабеля' in spec_data:

                replacements['ДЛИНА КАБЕЛЯ'] = str(spec_data['Длина кабеля'])

            
                                               

            if 'НАПРЯЖЕНИЕ' in spec_data:

                replacements['НАПРЯЖЕНИЕ'] = str(spec_data['НАПРЯЖЕНИЕ'])

            if 'Напряжение' in spec_data:

                replacements['НАПРЯЖЕНИЕ'] = str(spec_data['Напряжение'])

                    

            if 'EX' in spec_data:

                replacements['EX'] = str(spec_data['EX'])

            if 'Взрывозащита' in spec_data:

                ex_value = str(spec_data['Взрывозащита'])

                ex_lower = ex_value.lower()

                if 'согласован' in ex_lower:

                    replacements['EX'] = ex_value

                elif 'да' in ex_lower or 'yes' in ex_lower:

                    replacements['EX'] = 'да'

                else:

                    replacements['EX'] = 'нет'

            
  

            if 'Частота' in spec_data:

                replacements['ЧАСТОТА'] = str(spec_data['Частота'])

            


            if 'МОЩНОСТЬ' in spec_data:

                replacements['МОЩНОСТЬ'] = str(spec_data['МОЩНОСТЬ'])

            if 'Мощность' in spec_data:

                replacements['МОЩНОСТЬ'] = str(spec_data['Мощность'])

                                                    

            if 'Мощность на валу' in spec_data:

                replacements['P2'] = str(spec_data['Мощность на валу'])

            if 'МОЩНОСТЬ НА ВАЛУ' in spec_data:

                replacements['P2'] = str(spec_data['МОЩНОСТЬ НА ВАЛУ'])

            if 'P2' in spec_data:

                replacements['P2'] = str(spec_data['P2'])

              

            if 'Полюсы' in spec_data:

                replacements['ПОЛЮСЫ'] = str(spec_data['Полюсы'])

            if 'Число полюсов' in spec_data:

                replacements['ЧИСЛО ПОЛЮСОВ'] = str(spec_data['Число полюсов'])

            
                      

            if 'Изоляция' in spec_data:

                replacements['ИЗОЛЯЦИЯ'] = str(spec_data['Изоляция'])

            if 'Класс изоляции' in spec_data:

                replacements['КЛАСС ИЗОЛЯЦИИ'] = str(spec_data['Класс изоляции'])

                     

            if 'Защита' in spec_data:

                replacements['ЗАЩИТА'] = str(spec_data['Защита'])

            
                        

            if 'ТОК' in spec_data:

                replacements['ТОК'] = str(spec_data['ТОК'])

            if 'Ток' in spec_data:

                replacements['ТОК'] = str(spec_data['Ток'])

            if 'Номинальный ток' in spec_data:

                replacements['НОМИНАЛЬНЫЙ ТОК'] = str(spec_data['Номинальный ток'])

            
                                              

            if 'УЛИТКА' in spec_data:

                replacements['УЛИТКА'] = str(spec_data['УЛИТКА'])

            if 'Материал корпуса насоса (улитка)' in spec_data:

                replacements['УЛИТКА'] = str(spec_data['Материал корпуса насоса (улитка)'])

                            

            if 'ВАЛ' in spec_data:

                replacements['ВАЛ'] = str(spec_data['ВАЛ'])

            if 'Материал вала' in spec_data:

                replacements['ВАЛ'] = str(spec_data['Материал вала'])

                                             

            if 'ДАТЧИКИ' in spec_data:

                replacements['ДАТЧИКИ'] = str(spec_data['ДАТЧИКИ'])

                                                     

            if 'ПЧ' in spec_data:

                replacements['ПЧ'] = str(spec_data['ПЧ'])

            if 'УСТАНОВКА' in spec_data:

                install_value = str(spec_data['УСТАНОВКА'])

                full_install_value = install_value
                

                if 'КОММЕНТАРИЙ' in spec_data and spec_data['КОММЕНТАРИЙ']:

                    comment_value = str(spec_data['КОММЕНТАРИЙ'])

                    full_install_value = f"{full_install_value}\nКомментарий: {comment_value}"

                
                                                                          

                if 'АКСЕССУАРЫ' in spec_data and spec_data['АКСЕССУАРЫ']:

                    accessories_value = str(spec_data['АКСЕССУАРЫ'])

                    full_install_value = f"{full_install_value}\n{accessories_value}"

                                                                                                   

                replacements['УСТАНОВКА'] = full_install_value

                
                                                                                                 

                if 'КОММЕНТАРИЙ' in spec_data and spec_data['КОММЕНТАРИЙ']:

                    comment_value = str(spec_data['КОММЕНТАРИЙ'])

                    combined_value = f"{install_value}\nКомментарий: {comment_value}"

                    replacements['УСТАНОВКА\nКОММЕНТАРИЙ'] = combined_value

                    replacements['УСТАНОВКА КОММЕНТАРИЙ'] = combined_value

                

                if 'АКСЕССУАРЫ' in spec_data and spec_data['АКСЕССУАРЫ']:

                    accessories_value = str(spec_data['АКСЕССУАРЫ'])

                    if 'КОММЕНТАРИЙ' in spec_data and spec_data['КОММЕНТАРИЙ']:

                        comment_value = str(spec_data['КОММЕНТАРИЙ'])

                        combined_value = f"{install_value}\nКомментарий: {comment_value}\n{accessories_value}"

                    else:

                        combined_value = f"{install_value}\n{accessories_value}"

                    replacements['УСТАНОВКА\nАКСЕССУАРЫ'] = combined_value

                    replacements['УСТАНОВКА АКСЕССУАРЫ'] = combined_value

                                                                      

            if 'КОММЕНТАРИЙ' in spec_data:

                replacements['КОММЕНТАРИЙ'] = str(spec_data['КОММЕНТАРИЙ'])

                                                                       

            if 'АКСЕССУАРЫ' in spec_data:

                replacements['АКСЕССУАРЫ'] = str(spec_data['АКСЕССУАРЫ'])
                                                               

            if 'МАТЕРИАЛ' in spec_data:

                replacements['МАТЕРИАЛ'] = str(spec_data['МАТЕРИАЛ'])

            
            try:

                from docx import Document

                

                doc = Document(tp_docx_path)

                                                                                               

                def replace_in_paragraph(paragraph):

                    full_text = paragraph.text

                    if not full_text:

                        return

                    

                    needs_replace = False

                    replaced_text = full_text

                                                                    

                    sorted_replacements = sorted(replacements.items(), key=lambda x: len(x[0]), reverse=True)

                                                                                 

                    import re

                    for old_text, new_text in sorted_replacements:

                                                                 

                        pattern = re.escape(old_text)

                                                

                        matches = list(re.finditer(pattern, replaced_text, re.IGNORECASE))

                                                                                

                        for match in reversed(matches):

                            start, end = match.span()

                            matched_text = replaced_text[start:end]

                                                                                               

                                                                                                          

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

                

                for paragraph in doc.paragraphs:

                    replace_in_paragraph(paragraph)

                                 

                for table in doc.tables:

                    for row in table.rows:

                        for cell in row.cells:

                            for paragraph in cell.paragraphs:

                                replace_in_paragraph(paragraph)

                

                doc.save(modified_docx_path)

                

            except Exception as e:

                                                                     

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

                                                                                          

                                for old_text, new_text in sorted_replacements:

                                                                                    

                                    pattern = re.escape(old_text)

                                    matches = list(re.finditer(pattern, elem.text, re.IGNORECASE))

                                    for match in reversed(matches):

                                        start, end = match.span()

                                        matched = elem.text[start:end]

                                        if matched.isupper():

                                            elem.text = elem.text[:start] + new_text + elem.text[end:]

                            if elem.tail:

                                                     

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

                                                                                        

                        import re

                        for old_text, new_text in sorted_replacements:

                                                                            

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

                             

            tp_pdf_path = os.path.join(temp_dir, 'ТП_modified.pdf')

                                                                  

            pdf_converted = False

            libreoffice_paths = ['libreoffice', 'soffice']

            for lo_path in libreoffice_paths:

                try:

                    result = subprocess.run(

                        [lo_path, '--headless', '--convert-to', 'pdf', '--outdir', temp_dir, modified_docx_path],

                        capture_output=True,

                        timeout=60,

                        cwd=temp_dir,

                        check=False

                    )

                    if result.returncode == 0:

                        for name in ('ТП_modified.pdf', 'tp_modified.pdf', 'ТП_modified.pdf'):

                            p = os.path.join(temp_dir, name)

                            if os.path.exists(p) and os.path.getsize(p) > 0:

                                tp_pdf_path = p

                                pdf_converted = True

                                print(f"✅ PDF создан через LibreOffice для ТП.docx ({os.path.getsize(p)} байт)")

                                break

                    if pdf_converted:

                        break

                except (FileNotFoundError, subprocess.TimeoutExpired):

                    continue


            if not pdf_converted:

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

                                                                   

                                doc.Close(False)

                                
                                del doc
    

                                word.Quit(SaveChanges=False)

                                word = None

                                

                                                                     

                                import time

                                time.sleep(1.0)

                                

                                                                          

                                max_wait = 8                                          

                                wait_interval = 0.2

                                waited = 0

                                while waited < max_wait:

                                    time.sleep(wait_interval)

                                    waited += wait_interval

                                                                                                      

                                    try:

                                        if os.path.exists(tp_pdf_path):

                                            file_size = os.path.getsize(tp_pdf_path)

                                            if file_size > 0:

                                                                                 

                                                with open(tp_pdf_path, 'rb') as test_file:

                                                    test_file.read(1)

                                                                          

                                                pdf_converted = True

                                                print(f"✅ PDF создан через MS Word для ТП.docx ({file_size} байт)")

                                                break

                                    except (PermissionError, IOError, OSError) as file_err:

                                                                          

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

                                                                    

            import time

            if pdf_converted:

                                                                                      

                time.sleep(0.3)

                                                                  

                max_retries = 15

                retry_count = 0

                file_ready = False

                

                while retry_count < max_retries:

                    try:

                        if os.path.exists(tp_pdf_path):

                            file_size = os.path.getsize(tp_pdf_path)

                            if file_size > 0:

                                                                 

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

                                                                                           

            try:

                with open(tp_pdf_path, 'rb') as pdf_file:

                    pdf_data = pdf_file.read()

                                             

                pdf_buffer = BytesIO(pdf_data)

                pdf_buffer.seek(0)

                                       

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


P_INST_PLACEHOLDER_KEYS = ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'k', 'l', 'm', 'n', 'o', 'r']

APP_ROOT = os.path.dirname(os.path.abspath(__file__))

FONTS_DIR = os.path.join(APP_ROOT, 'fonts')

GOST_AU_FONT_FILE = os.path.join(FONTS_DIR, 'GOST_AU.ttf')

P_INST_LINUX_FONT = 'Liberation Sans'

P_INST_WORD_CONVERTER_URL = os.environ.get('P_INST_WORD_CONVERTER_URL', '').strip()

P_INST_WORD_CONVERTER_SECRET = os.environ.get('P_INST_WORD_CONVERTER_SECRET', '').strip()

P_INST_XFRM_ROT_TO_VERT = {
    '16200000': 'vert270',
    '5400000': 'vert',
    '2700000': 'eaVert',
}


def _gost_font_available():

    return os.path.isfile(GOST_AU_FONT_FILE)


def _build_lo_fontconfig_env(temp_dir):

    """FONTCONFIG_FILE для LibreOffice — подхват шрифтов из fonts/."""

    env = os.environ.copy()

    if not _gost_font_available():

        return env

    fonts_conf = os.path.join(temp_dir, 'fonts.conf')

    cache_dir = os.path.join(temp_dir, 'fontconfig-cache')

    os.makedirs(cache_dir, exist_ok=True)

    fonts_dir = FONTS_DIR.replace('\\', '/')

    with open(fonts_conf, 'w', encoding='utf-8') as conf_file:

        conf_file.write(

            '<?xml version="1.0"?>\n'

            '<!DOCTYPE fontconfig SYSTEM "fonts.dtd">\n'

            '<fontconfig>\n'

            f'  <dir>{fonts_dir}</dir>\n'

            f'  <cachedir>{cache_dir.replace(chr(92), "/")}</cachedir>\n'

            '</fontconfig>\n'

        )

    env['FONTCONFIG_FILE'] = fonts_conf

    return env


def _strip_p_inst_txbx_background(block):

    """Убирает белую заливку текстовых полей — LibreOffice рисует её поверх фона чертежа."""

    import re

    if 'txbxContent' not in block and 'wps:txbx' not in block:

        return block

    def fix_sppr(sppr_match):

        sppr = sppr_match.group(0)

        sppr = re.sub(r'<a:solidFill>.*?</a:solidFill>\s*', '', sppr, flags=re.DOTALL)

        if '<a:noFill/>' not in sppr:

            sppr = re.sub(r'(<(?:wps:|pic:)spPr[^>]*>)', r'\1<a:noFill/>', sppr, count=1)

        return sppr

    block = re.sub(r'<(?:wps:|pic:)spPr>.*?</(?:wps:|pic:)spPr>', fix_sppr, block, flags=re.DOTALL)

    def fix_vshape(m):

        shape = m.group(0)

        shape = re.sub(r'\s*fillcolor="[^"]*"', '', shape)

        if 'filled="' not in shape:

            shape = shape.replace('<v:shape ', '<v:shape filled="f" ', 1)

        else:

            shape = re.sub(r'filled="[^"]*"', 'filled="f"', shape)

        style_m = re.search(r'style="([^"]*)"', shape)

        if style_m:

            style = re.sub(r'fill:\s*[^;"]+;?', '', style_m.group(1), flags=re.IGNORECASE).rstrip(';')

            if 'fill:' not in style.lower():

                style = (style + ';fill:none') if style else 'fill:none'

            shape = shape.replace(f'style="{style_m.group(1)}"', f'style="{style}"', 1)

        return shape

    block = re.sub(r'<v:shape[^>]*>.*?</v:shape>', fix_vshape, block, flags=re.DOTALL)

    block = re.sub(r'<w:shd[^>]*/>', '', block)

    block = re.sub(r'<w:highlight[^>]*/>', '', block)

    return block


def _strip_p_inst_txbx_backgrounds(xml_str):

    """Прозрачный фон у всех текстовых полей-размеров в P_inst.docx."""

    import re

    return re.sub(

        r'<wp:anchor[^>]*>.*?</wp:anchor>',

        lambda m: _strip_p_inst_txbx_background(m.group(0)),

        xml_str,

        flags=re.DOTALL,

    )


def _fix_p_inst_xml_for_libreoffice(xml_str):

    """LibreOffice: прозрачные плейсхолдеры txbx; rot переносим в wps:bodyPr vert."""

    import re

    import sys

    xml_str = _strip_p_inst_txbx_backgrounds(xml_str)

    if sys.platform == 'win32':

        return xml_str

    if not _gost_font_available():

        xml_str = xml_str.replace('GOST Type AU', P_INST_LINUX_FONT)

    def fix_anchor(match):

        block = match.group(0)

        rot_m = re.search(r'<a:xfrm rot="(\d+)"', block)

        if not rot_m:

            return block

        rot_val = rot_m.group(1)

        if rot_val == '0':

            return block

        vert_val = P_INST_XFRM_ROT_TO_VERT.get(rot_val)

        if not vert_val:

            return block

        wp_ext = re.search(r'<wp:extent cx="(\d+)" cy="(\d+)"/>', block)

        wcx = int(wp_ext.group(1)) if wp_ext else 0

        block = re.sub(r'(<a:xfrm) rot="\d+"', r'\1 rot="0"', block, count=1)

        ext_m = re.search(r'<a:ext cx="(\d+)" cy="(\d+)"/>', block)

        if ext_m and rot_val in ('16200000', '5400000'):

            cx, cy = ext_m.group(1), ext_m.group(2)

            block = block.replace(

                f'<a:ext cx="{cx}" cy="{cy}"/>',

                f'<a:ext cx="{cy}" cy="{cx}"/>',

                1,

            )

        if 'wps:bodyPr' in block:

            if re.search(r'vert="[^"]+"', block):

                block = re.sub(

                    r'(<wps:bodyPr[^>]*?)vert="[^"]+"',

                    rf'\1vert="{vert_val}"',

                    block,

                    count=1,

                )

            else:

                block = re.sub(

                    r'(<wps:bodyPr[^>]*?)(\s*/>)',

                    rf'\1 vert="{vert_val}"\2',

                    block,

                    count=1,

                )

        if rot_val == '16200000' and wcx:

            block = re.sub(

                r'(<wp:positionV relativeFrom="paragraph">\s*<wp:posOffset>)(-?\d+)(</wp:posOffset>)',

                lambda m: f"{m.group(1)}{int(m.group(2)) + wcx}{m.group(3)}",

                block,

                count=1,

            )

        return block

    return re.sub(r'<wp:anchor[^>]*>.*?</wp:anchor>', fix_anchor, xml_str, flags=re.DOTALL)


def _fill_p_inst_docx(source_docx, output_docx, values):

    """Заполнение P_inst.docx, включая подписи на чертеже в word/document.xml."""

    import zipfile

    import re

    allowed = set(values.keys())

    with zipfile.ZipFile(source_docx, 'r') as source:

        file_contents = {item.filename: source.read(item.filename) for item in source.infolist()}

    xml_bytes = file_contents.get('word/document.xml')

    if xml_bytes is None:

        raise FileNotFoundError('word/document.xml не найден в P_inst.docx')

    xml_str = xml_bytes.decode('utf-8')

    # До подстановки значений: иначе плейсхолдеры уже не распознать как одну букву.
    xml_str = _strip_p_inst_txbx_backgrounds(xml_str)

    def replace_wt_tag(match):

        open_tag, inner, close_tag = match.group(1), match.group(2), match.group(3)

        key = inner.strip()

        if key in allowed:

            return open_tag + values[key] + close_tag

        return match.group(0)

    xml_str = re.sub(r'(<w:t[^>]*>)([^<]*)(</w:t>)', replace_wt_tag, xml_str)

    xml_str = _fix_p_inst_xml_for_libreoffice(xml_str)

    file_contents['word/document.xml'] = xml_str.encode('utf-8')

    with zipfile.ZipFile(output_docx, 'w', zipfile.ZIP_DEFLATED) as target:

        for filename, content in file_contents.items():

            target.writestr(filename, content)


def _convert_docx_to_pdf_via_word_com(docx_path, pdf_path):

    """Конвертация DOCX в PDF через MS Word (только Windows)."""

    import sys

    if sys.platform != 'win32':

        return False

    try:

        import win32com.client

        import pythoncom

        pythoncom.CoInitialize()

        word = None

        try:

            word = win32com.client.Dispatch("Word.Application")

            word.Visible = False

            word.DisplayAlerts = 0

            doc_path = os.path.abspath(docx_path).replace('/', '\\')

            doc = word.Documents.Open(doc_path, ReadOnly=True, ConfirmConversions=False, AddToRecentFiles=False)

            out_path = os.path.abspath(pdf_path).replace('/', '\\')

            doc.SaveAs2(FileName=out_path, FileFormat=17)

            doc.Close(False)

            del doc

            return os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0

        finally:

            if word is not None:

                word.Quit()

            pythoncom.CoUninitialize()

    except Exception as e:

        print(f"⚠️ MS Word конвертация не удалась: {e}")

        return False


def _convert_docx_to_pdf_via_remote_word(docx_path, pdf_path):

    """Конвертация через удалённый Windows-сервис с MS Word (POST docx → PDF)."""

    if not P_INST_WORD_CONVERTER_URL:

        return False

    try:

        headers = {}

        if P_INST_WORD_CONVERTER_SECRET:

            headers['X-Converter-Secret'] = P_INST_WORD_CONVERTER_SECRET

        with open(docx_path, 'rb') as docx_file:

            response = requests.post(

                P_INST_WORD_CONVERTER_URL,

                files={'file': (os.path.basename(docx_path), docx_file, 'application/vnd.openxmlformats-officedocument.wordprocessingml.document')},

                headers=headers,

                timeout=120,

            )

        if response.status_code != 200:

            print(f"⚠️ Удалённый Word-конвертер: HTTP {response.status_code}")

            return False

        content_type = (response.headers.get('Content-Type') or '').lower()

        if 'pdf' not in content_type and not response.content.startswith(b'%PDF'):

            print("⚠️ Удалённый Word-конвертер вернул не PDF")

            return False

        with open(pdf_path, 'wb') as pdf_file:

            pdf_file.write(response.content)

        return os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0

    except Exception as e:

        print(f"⚠️ Удалённый Word-конвертер: {e}")

        return False


def _convert_docx_to_pdf(docx_path, pdf_path, temp_dir, embed_fonts=False, prefer_word=False, use_bundled_fonts=False):

    """Конвертация DOCX в PDF (Word / удалённый Word / LibreOffice / docx2pdf)."""

    import shutil

    import sys

    pdf_converted = False

    base_name = os.path.splitext(os.path.basename(docx_path))[0]

    if prefer_word:

        if _convert_docx_to_pdf_via_remote_word(docx_path, pdf_path):

            return True

        if _convert_docx_to_pdf_via_word_com(docx_path, pdf_path):

            return True

    libreoffice_paths = ['libreoffice', 'soffice']

    if sys.platform == 'win32':

        libreoffice_paths.extend([

            r'C:\Program Files\LibreOffice\program\soffice.exe',

            r'C:\Program Files (x86)\LibreOffice\program\soffice.exe',

        ])

    lo_profile = os.path.join(temp_dir, 'lo_profile')

    os.makedirs(lo_profile, exist_ok=True)

    lo_user_install = f'-env:UserInstallation=file:///{lo_profile.replace(os.sep, "/")}'

    lo_env = _build_lo_fontconfig_env(temp_dir) if use_bundled_fonts else None

    if embed_fonts:

        lo_pdf_targets = [

            'pdf:writer_pdf_Export:{"EmbedStandardFonts":{"type":"boolean","value":"true"},"UseTaggedPDF":{"type":"boolean","value":"false"}}',

            'pdf',

        ]

    else:

        lo_pdf_targets = ['pdf']

    for lo_path in libreoffice_paths:

        for convert_to in lo_pdf_targets:

            try:

                result = subprocess.run(

                    [

                        lo_path,

                        lo_user_install,

                        '--headless',

                        '--convert-to',

                        convert_to,

                        '--outdir',

                        temp_dir,

                        docx_path,

                    ],

                    capture_output=True,

                    timeout=90,

                    cwd=temp_dir,

                    check=False,

                    env=lo_env,

                )

                if result.returncode == 0:

                    for name in (f'{base_name}.pdf', f'{base_name.lower()}.pdf'):

                        p = os.path.join(temp_dir, name)

                        if os.path.exists(p) and os.path.getsize(p) > 0:

                            if os.path.abspath(p) != os.path.abspath(pdf_path):

                                shutil.copy2(p, pdf_path)

                            pdf_converted = True

                            break

                if pdf_converted:

                    break

            except (FileNotFoundError, subprocess.TimeoutExpired):

                continue

        if pdf_converted:

            break

    if not pdf_converted and not prefer_word:

        if _convert_docx_to_pdf_via_remote_word(docx_path, pdf_path):

            pdf_converted = True

    if not pdf_converted:

        if _convert_docx_to_pdf_via_word_com(docx_path, pdf_path):

            pdf_converted = True

    if not pdf_converted:

        try:

            from docx2pdf import convert

            convert(docx_path, pdf_path)

            if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0:

                pdf_converted = True

        except Exception as e:

            print(f"⚠️ docx2pdf: {e}")

    return pdf_converted and os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0


def _convert_p_inst_docx_to_pdf(docx_path, pdf_path, temp_dir):

    """P_inst: удалённый Word → локальный Word → LibreOffice с GOST."""

    return _convert_docx_to_pdf(

        docx_path,

        pdf_path,

        temp_dir,

        embed_fonts=True,

        prefer_word=True,

        use_bundled_fonts=True,

    )


@app.route('/api/internal/convert-docx-to-pdf', methods=['POST'])

def internal_convert_docx_to_pdf():

    """
    Внутренний endpoint для удалённой конвертации DOCX→PDF через MS Word.
    Запускайте на Windows-машине с Word; Linux-сервер вызывает по P_INST_WORD_CONVERTER_URL.
    Заголовок: X-Converter-Secret = P_INST_WORD_CONVERTER_SECRET
    """

    import sys

    if sys.platform != 'win32':

        return jsonify({"error": "Требуется Windows с установленным MS Word"}), 503

    expected_secret = P_INST_WORD_CONVERTER_SECRET

    if not expected_secret:

        return jsonify({"error": "P_INST_WORD_CONVERTER_SECRET не задан на сервере"}), 503

    if request.headers.get('X-Converter-Secret') != expected_secret:

        return jsonify({"error": "Неверный секрет"}), 401

    upload = request.files.get('file')

    if upload is None or not upload.filename:

        return jsonify({"error": "Нужен файл в поле file"}), 400

    try:

        with tempfile.TemporaryDirectory() as temp_dir:

            docx_path = os.path.join(temp_dir, 'input.docx')

            pdf_path = os.path.join(temp_dir, 'output.pdf')

            upload.save(docx_path)

            if not _convert_docx_to_pdf_via_word_com(docx_path, pdf_path):

                return jsonify({"error": "MS Word не смог сконвертировать файл"}), 500

            with open(pdf_path, 'rb') as pdf_file:

                pdf_data = pdf_file.read()

            return send_file(

                BytesIO(pdf_data),

                mimetype='application/pdf',

                as_attachment=False,

                download_name='converted.pdf',

            )

    except Exception as e:

        print(f"❌ internal convert-docx-to-pdf: {e}")

        return jsonify({"error": str(e)}), 500


@app.route('/api/generate-p-inst', methods=['POST'])

@login_required

def generate_p_inst():

    """
    Генерация чертежа П-установки из P_inst.docx с подстановкой размеров.
    Только для администраторов.
    POST /api/generate-p-inst
    Body: { "values": { "a": "100", "b": "200", ... } }
    """

    if not current_user.is_admin:

        return jsonify({"error": "Доступ только для администраторов"}), 403

    import shutil

    try:

        data = request.get_json() or {}

        raw_values = data.get('values') or {}

        values = {}

        for key in P_INST_PLACEHOLDER_KEYS:

            values[key] = str(raw_values.get(key, ''))

        p_inst_docx_path = os.path.join(os.path.dirname(__file__), 'P_inst.docx')

        if not os.path.exists(p_inst_docx_path):

            return jsonify({"error": "Файл P_inst.docx не найден"}), 404

        with tempfile.TemporaryDirectory() as temp_dir:

            modified_docx_path = os.path.join(temp_dir, 'P_inst_modified.docx')

            pdf_path = os.path.join(temp_dir, 'P_inst_modified.pdf')

            try:

                _fill_p_inst_docx(p_inst_docx_path, modified_docx_path, values)

            except Exception as e:

                print(f"⚠️ Заполнение P_inst.docx: {e}")

                return jsonify({"error": f"Ошибка при заполнении P_inst.docx: {e}"}), 500

            if not _convert_p_inst_docx_to_pdf(modified_docx_path, pdf_path, temp_dir):

                hint = "Не удалось конвертировать P_inst.docx в PDF."

                if not _gost_font_available():

                    hint += " Установите шрифт: sudo bash scripts/install_fonts.sh"

                if not P_INST_WORD_CONVERTER_URL:

                    hint += " Для точного совпадения с Windows задайте P_INST_WORD_CONVERTER_URL."

                return jsonify({"error": hint}), 500

            with open(pdf_path, 'rb') as pdf_file:

                pdf_data = pdf_file.read()

            pdf_buffer = BytesIO(pdf_data)

            pdf_buffer.seek(0)

            return send_file(

                pdf_buffer,

                mimetype='application/pdf',

                as_attachment=False,

                download_name='p_inst_drawing.pdf'

            )

    except Exception as e:

        print(f"❌ Ошибка при генерации P_inst: {e}")

        import traceback

        traceback.print_exc()

        return jsonify({"error": f"Ошибка при генерации P_inst: {e}"}), 500


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



@app.errorhandler(404)

def not_found(error):

    """Обработка 404 ошибки"""

    return jsonify({"error": "Страница не найдена"}), 404



@app.errorhandler(500)

def internal_error(error):

    """Обработка 500 ошибки"""

    return jsonify({"error": "Внутренняя ошибка сервера"}), 500



@app.route('/<path:path>')

def serve_static(path):

    """Отдача статических файлов. data1.json не отдаём — данные встроены в страницы select/result."""

    if path.strip().lower() == 'data1.json':

        return jsonify({"error": "Доступ запрещён"}), 403

    if path.startswith('api/'):

        return jsonify({"error": f"API endpoint not found: /{path}"}), 404

    return send_from_directory('.', path)


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

    print("   /select.html   - Подбор насоса")

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

    

                      

                                                                     

    port = int(os.environ.get('PORT', 5000))

    debug_mode = os.environ.get('FLASK_ENV') != 'production'

    

    app.run(

        host='0.0.0.0',                              

        port=port,                                                            

        debug=debug_mode                                     

    )




import os
from werkzeug.utils import secure_filename
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from datetime import datetime

app = Flask(__name__)
app.config['SECRET_KEY'] = 'super-secret-nookly-key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///nookly.db'
app.config['UPLOAD_FOLDER'] = os.path.join('static', 'uploads')

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)

# --- НАСТРОЙКА FLASK-LOGIN ---
login_manager = LoginManager(app)
login_manager.login_view = 'login'  # Куда перенаправлять, если неавторизованный юзер лезет в закрытую часть
login_manager.login_message = "Пожалуйста, войдите, чтобы открыть эту страницу."


# --- МОДЕЛЬ БАЗЫ ДАННЫХ ---
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    posts = db.relationship('Post', backref='author', lazy=True)

class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    image_file = db.Column(db.String(100), nullable=True)
    date_posted = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    likes = db.relationship('Like', backref='post', lazy=True, cascade="all, delete-orphan")

class Like(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)


# Эта функция помогает Flask-Login находить пользователя в базе по его ID в сессии
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- РОУТЫ (МАРШРУТЫ) ---

# 1. Главная страница (Лента постов)
@app.route('/')
def index():
    # Получаем все посты из базы данных, сортируем по дате (самые новые сверху)
    posts = Post.query.order_by(Post.date_posted.desc()).all()
    return render_template('index.html', posts=posts)

# Новый роут для создания поста
@app.route('/create_post', methods=['POST'])
@login_required # Только для авторизованных
def create_post():
    content = request.form.get('content')
    image = request.files.get('image')  # Получаем файл из формы

    filename = None

    # Если пользователь прикрепил файл и у файла есть имя
    if image and image.filename != '':
        # Обезопасим имя файла
        filename = secure_filename(image.filename)
        # Сохраняем файл в папку static/uploads
        image.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

    # Создаем пост (даже если есть только текст или только картинка)
    if content or filename:
        new_post = Post(content=content, image_file=filename, user_id=current_user.id)
        db.session.add(new_post)
        db.session.commit()
        flash('Пост успешно опубликован!', 'success')

    return redirect(url_for('index'))


# 2. Регистрация (осталась почти такой же)
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            flash('Пользователь с таким именем уже существует!', 'error')
            return redirect(url_for('register'))

        hashed_pw = generate_password_hash(password)
        new_user = User(username=username, password_hash=hashed_pw)
        db.session.add(new_user)
        db.session.commit()

        flash('Регистрация прошла успешно! Теперь вы можете войти.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')


# 3. Вход (Логин)
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        # Ищем пользователя в базе
        user = User.query.filter_by(username=username).first()

        # Если юзер есть и пароль (расшифрованный) совпадает
        if user and check_password_hash(user.password_hash, password):
            login_user(user)  # Запоминаем юзера в сессии
            return redirect(url_for('index'))  # Отправляем на главную
        else:
            flash('Неверное имя пользователя или пароль.', 'error')

    return render_template('login.html')


# 4. Выход из аккаунта
@app.route('/logout')
@login_required  # Доступно только авторизованным
def logout():
    logout_user()  # Удаляем юзера из сессии
    return redirect(url_for('index'))

# 5. Оценки
@app.route('/like/<int:post_id>')
@login_required
def like_post(post_id):
    # Ищем, ставил ли уже этот юзер лайк этому посту
    like = Like.query.filter_by(user_id=current_user.id, post_id=post_id).first()

    if like:
        # Если лайк уже есть — удаляем его (убираем лайк)
        db.session.delete(like)
    else:
        # Если лайка нет — создаем новый
        new_like = Like(user_id=current_user.id, post_id=post_id)
        db.session.add(new_like)

    db.session.commit()
    # Возвращаемся на главную страницу, где были
    return redirect(url_for('index'))


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
import os
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from datetime import datetime
import uuid
from PIL import Image
from flask import send_from_directory


app = Flask(__name__)
app.config['SECRET_KEY'] = 'super-secret-nookly-key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///nookly.db'
app.config['UPLOAD_FOLDER'] = os.path.join('static', 'uploads')

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)

# --- НАСТРОЙКА FLASK-LOGIN ---
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = "Пожалуйста, войдите, чтобы открыть эту страницу."


# --- МОДЕЛЬ БАЗЫ ДАННЫХ ---
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    posts = db.relationship('Post', backref='author', lazy=True)

class Like(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)


class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    text = db.Column(db.Text, nullable=False)
    date_posted = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey('comment.id'), nullable=True)
    author = db.relationship('User', backref='user_comments')
    replies = db.relationship('Comment', backref=db.backref('parent', remote_side=[id]), lazy=True,
                              cascade="all, delete-orphan")


class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    image_file = db.Column(db.String(100), nullable=True)
    date_posted = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    views = db.Column(db.Integer, default=0)
    likes = db.relationship('Like', backref='post', lazy=True, cascade="all, delete-orphan")
    comments = db.relationship('Comment', backref='post', lazy=True, cascade="all, delete-orphan")


# Эта функция помогает Flask-Login находить пользователя в базе по его ID в сессии
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- РОУТЫ ---

# 1. Главная страница (Лента постов)
@app.route('/')
def index():
    sort = request.args.get('sort', 'new')
    page = request.args.get('page', 1, type=int)

    if sort == 'popular':
        query = Post.query.outerjoin(Like).group_by(Post.id).order_by(db.func.count(Like.id).desc(), Post.date_posted.desc())
    else:
        query = Post.query.order_by(Post.date_posted.desc())

    posts_pagination = query.paginate(page=page, per_page=5)

    if page == 1:
        for post in posts_pagination.items:
            post.views += 1
        db.session.commit()

    return render_template('index.html', posts_pagination=posts_pagination, sort=sort)


# 2. Регистрация
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


# 3. Вход
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        user = User.query.filter_by(username=username).first()

        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for('index'))
        else:
            flash('Неверное имя пользователя или пароль.', 'error')

    return render_template('login.html')


# 4. Выход из аккаунта
@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))


# 5. Оценки
@app.route('/like/<int:post_id>', methods=['POST'])
@login_required
def like_post(post_id):
    post = Post.query.get_or_404(post_id)
    like = Like.query.filter_by(user_id=current_user.id, post_id=post_id).first()

    if like:
        db.session.delete(like)
        liked = False
    else:
        new_like = Like(user_id=current_user.id, post_id=post_id)
        db.session.add(new_like)
        liked = True

    db.session.commit()

    return jsonify({
        'liked': liked,
        'likes_count': len(post.likes)
    })


# 6. Посты
@app.route('/post/<int:post_id>')
def view_post(post_id):
    post = Post.query.get_or_404(post_id)

    post.views += 1
    db.session.commit()

    return render_template('post.html', post=post)


# 7. Комментарий
@app.route('/comment/<int:post_id>', methods=['POST'])
@login_required
def add_comment(post_id):
    text = request.form.get('text')
    parent_id = request.form.get('parent_id')

    if text:
        new_comment = Comment(
            text=text,
            post_id=post_id,
            user_id=current_user.id,
            parent_id=parent_id if parent_id else None
        )
        db.session.add(new_comment)
        db.session.commit()

    return redirect(url_for('view_post', post_id=post_id))


# 8. Скрытие пути картинок
@app.route('/media/<string:filename>')
def serve_image(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


# 9. Создание постов
@app.route('/create_post', methods=['POST'])
@login_required
def create_post():
    content = request.form.get('content')
    image = request.files.get('image')

    filename = None
    sezi = 20 * 1024 * 1024

    if image and image.filename != '':
        image.seek(0, os.SEEK_END)
        file_size = image.tell()
        image.seek(0)

        if file_size > sezi:
            flash('Файл слишком большой! Максимальный размер 20 МБ.', 'error')
            return redirect(url_for('index'))

        ext = image.filename.rsplit('.', 1)[1].lower() if '.' in image.filename else 'jpg'
        filename = f"{uuid.uuid4().hex}.{ext}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)

        img = Image.open(image)

        if img.mode in ("RGBA", "P"):
            img.save(filepath)
        else:
            img = img.convert("RGB")
            img.save(filepath)

    if content or filename:
        new_post = Post(content=content, image_file=filename, user_id=current_user.id)
        db.session.add(new_post)
        db.session.commit()
        flash('Пост успешно опубликован!', 'success')

    return redirect(url_for('index'))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host="0.0.0.0", port=5000, debug=True)
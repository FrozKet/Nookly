import os
from werkzeug.utils import secure_filename
from flask import Flask, render_template, request, redirect, url_for, flash
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

login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = "Пожалуйста, войдите, чтобы открыть эту страницу."


class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    avatar = db.Column(db.String(100), nullable=True, default='default_avatar.png')
    bio = db.Column(db.Text, nullable=True, default='')
    date_joined = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    posts = db.relationship('Post', backref='author', lazy=True)

    def get_followers_count(self):
        return Follow.query.filter_by(followed_id=self.id).count()

    def get_following_count(self):
        return Follow.query.filter_by(follower_id=self.id).count()

    def get_total_likes_received(self):
        total_likes = db.session.query(db.func.count(Like.id)) \
            .join(Post, Like.post_id == Post.id) \
            .filter(Post.user_id == self.id) \
            .scalar()
        return total_likes or 0

    def is_following(self, user):
        if not current_user.is_authenticated:
            return False
        return Follow.query.filter_by(
            follower_id=current_user.id,
            followed_id=user.id
        ).first() is not None


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
    author = db.relationship('User', backref='user_comments')


class Follow(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    follower_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)  # кто
    followed_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)  # на кого
    date_followed = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('follower_id', 'followed_id', name='unique_follow'),
    )

    follower = db.relationship('User', foreign_keys=[follower_id], backref='following_relations')
    followed = db.relationship('User', foreign_keys=[followed_id], backref='follower_relations')


class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    image_file = db.Column(db.String(100), nullable=True)
    date_posted = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    views = db.Column(db.Integer, default=0)
    likes = db.relationship('Like', backref='post', lazy=True, cascade="all, delete-orphan")
    comments = db.relationship('Comment', backref='post', lazy=True, cascade="all, delete-orphan")


# загрузчик
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
        query = Post.query.outerjoin(Like).group_by(Post.id).order_by(db.func.count(Like.id).desc(),
                                                                      Post.date_posted.desc())
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
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))


# 5. Оценки
@app.route('/like/<int:post_id>')
@login_required
def like_post(post_id):
    like = Like.query.filter_by(user_id=current_user.id, post_id=post_id).first()

    if like:
        db.session.delete(like)
    else:
        new_like = Like(user_id=current_user.id, post_id=post_id)
        db.session.add(new_like)

    db.session.commit()

    return redirect(url_for('index'))


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
    if text:
        new_comment = Comment(text=text, post_id=post_id, user_id=current_user.id)
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

    if image and image.filename != '':
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


# 10 Профиль
# 10. Профиль пользователя
@app.route('/profile/<string:username>')
def profile(username):
    user = User.query.filter_by(username=username).first_or_404()

    # Получаем посты пользователя
    page = request.args.get('page', 1, type=int)
    posts_pagination = Post.query.filter_by(user_id=user.id) \
        .order_by(Post.date_posted.desc()) \
        .paginate(page=page, per_page=10)

    # Статистика
    followers_count = user.get_followers_count()
    following_count = user.get_following_count()
    total_likes = user.get_total_likes_received()

    # Проверяем подписку
    is_following = False
    if current_user.is_authenticated:
        is_following = current_user.is_following(user)

    return render_template('profile.html',
                           user=user,
                           posts_pagination=posts_pagination,
                           followers_count=followers_count,
                           following_count=following_count,
                           total_likes=total_likes,
                           is_following=is_following)


# 11. Редактирование профиля
@app.route('/edit_profile', methods=['GET', 'POST'])
@login_required
def edit_profile():
    if request.method == 'POST':
        bio = request.form.get('bio', '')
        avatar = request.files.get('avatar')

        # Обновляем био
        current_user.bio = bio

        # Обработка аватара
        if avatar and avatar.filename != '':
            ext = avatar.filename.rsplit('.', 1)[1].lower() if '.' in avatar.filename else 'jpg'
            filename = f"avatar_{current_user.id}_{uuid.uuid4().hex[:8]}.{ext}"
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)

            # Создаем аватар 150x150
            img = Image.open(avatar)
            img.thumbnail((150, 150), Image.Resampling.LANCZOS)

            if img.mode in ("RGBA", "P"):
                img.save(filepath)
            else:
                img = img.convert("RGB")
                img.save(filepath)

            # Удаляем старый аватар если не дефолтный
            if current_user.avatar and current_user.avatar != 'default_avatar.png':
                old_avatar_path = os.path.join(app.config['UPLOAD_FOLDER'], current_user.avatar)
                if os.path.exists(old_avatar_path):
                    os.remove(old_avatar_path)

            current_user.avatar = filename

        db.session.commit()
        flash('Профиль успешно обновлен!', 'success')
        return redirect(url_for('profile', username=current_user.username))

    return render_template('edit_profile.html')


# 12. Подписка/Отписка
@app.route('/follow/<string:username>')
@login_required
def follow_user(username):
    user_to_follow = User.query.filter_by(username=username).first_or_404()

    if user_to_follow.id == current_user.id:
        flash('Вы не можете подписаться на самого себя!', 'error')
        return redirect(url_for('profile', username=username))

    follow = Follow.query.filter_by(
        follower_id=current_user.id,
        followed_id=user_to_follow.id
    ).first()

    if follow:
        db.session.delete(follow)
        flash(f'Вы отписались от {username}', 'info')
    else:
        new_follow = Follow(follower_id=current_user.id, followed_id=user_to_follow.id)
        db.session.add(new_follow)
        flash(f'Вы подписались на {username}', 'success')

    db.session.commit()
    return redirect(url_for('profile', username=username))


# 13. Список подписчиков
@app.route('/profile/<string:username>/followers')
def followers(username):
    user = User.query.filter_by(username=username).first_or_404()

    followers_list = db.session.query(User, Follow.date_followed) \
        .join(Follow, User.id == Follow.follower_id) \
        .filter(Follow.followed_id == user.id) \
        .order_by(Follow.date_followed.desc()) \
        .all()

    return render_template('followers.html', user=user, followers=followers_list)


# 14. Список подписок
@app.route('/profile/<string:username>/following')
def following(username):
    user = User.query.filter_by(username=username).first_or_404()

    following_list = db.session.query(User, Follow.date_followed) \
        .join(Follow, User.id == Follow.followed_id) \
        .filter(Follow.follower_id == user.id) \
        .order_by(Follow.date_followed.desc()) \
        .all()

    return render_template('following.html', user=user, following=following_list)


# 15. Удаление поста
@app.route('/delete_post/<int:post_id>')
@login_required
def delete_post(post_id):
    post = Post.query.get_or_404(post_id)

    if post.user_id != current_user.id:
        flash('Вы не можете удалить этот пост!', 'error')
        return redirect(url_for('index'))

    # Удалить
    if post.image_file:
        image_path = os.path.join(app.config['UPLOAD_FOLDER'], post.image_file)
        if os.path.exists(image_path):
            os.remove(image_path)

    db.session.delete(post)
    db.session.commit()
    flash('Пост успешно удален!', 'success')

    return redirect(url_for('profile', username=current_user.username))


# 16. Мои посты
@app.route('/my_posts')
@login_required
def my_posts():
    return redirect(url_for('profile', username=current_user.username))


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host="0.0.0.0", port=5000, debug=True)

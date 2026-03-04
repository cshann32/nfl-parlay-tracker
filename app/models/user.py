import enum
from datetime import datetime, timezone
from flask_login import UserMixin
from app.extensions import db, login_manager, bcrypt


class UserRole(str, enum.Enum):
    ADMIN = "admin"
    USER = "user"
    VIEWER = "viewer"  # read-only: can view stats/news but cannot create parlays or upload


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.Enum(UserRole, name='userrole', create_type=False, native_enum=False, values_callable=lambda x: [m.value for m in x]), nullable=False, default=UserRole.USER)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    last_login = db.Column(db.DateTime(timezone=True), nullable=True)

    parlays = db.relationship("Parlay", back_populates="user", lazy="dynamic",
                              cascade="all, delete-orphan")
    documents = db.relationship("Document", back_populates="user", lazy="dynamic",
                                cascade="all, delete-orphan")
    reports = db.relationship("Report", back_populates="user", lazy="dynamic",
                              cascade="all, delete-orphan")

    def set_password(self, password: str) -> None:
        self.password_hash = bcrypt.generate_password_hash(password).decode("utf-8")

    def check_password(self, password: str) -> bool:
        return bcrypt.check_password_hash(self.password_hash, password)

    @property
    def is_admin(self) -> bool:
        return self.role == UserRole.ADMIN

    def __repr__(self) -> str:
        return f"<User {self.username} ({self.role.value})>"


@login_manager.user_loader
def load_user(user_id: str) -> User | None:
    return db.session.get(User, int(user_id))

import enum
from datetime import datetime, timezone
from app.extensions import db


class ParseStatus(str, enum.Enum):
    PENDING = "pending"
    SUCCESS = "success"
    PARTIAL = "partial"  # parsed but with skipped rows
    FAILED = "failed"


class Document(db.Model):
    __tablename__ = "documents"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    filename = db.Column(db.String(500), nullable=False)         # Stored filename (uuid-based)
    original_filename = db.Column(db.String(500), nullable=False)
    file_type = db.Column(db.String(20), nullable=False, index=True)  # pdf / csv / xlsx / image / json / xml
    file_size = db.Column(db.Integer, nullable=True)             # bytes
    upload_date = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    parsed_status = db.Column(
        db.Enum(ParseStatus, name='parsestatus', create_type=False,
                values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
        default=ParseStatus.PENDING,
    )
    parsed_data = db.Column(db.JSON, nullable=True)              # Extracted structured data
    rows_extracted = db.Column(db.Integer, nullable=True)
    rows_skipped = db.Column(db.Integer, nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    parser_used = db.Column(db.String(50), nullable=True)
    parsed_at = db.Column(db.DateTime(timezone=True), nullable=True)

    user = db.relationship("User", back_populates="documents")

    def __repr__(self) -> str:
        return f"<Document {self.original_filename} [{self.parsed_status.value}]>"

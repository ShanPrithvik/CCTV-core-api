from marshmallow import fields

from ..init import db, ma
from ..services.stream_security import mask_credentials

class Camera(db.Model):
    __tablename__ = 'Camera'

    id = db.Column(db.Integer, primary_key=True)
    camera_name = db.Column(db.String(50), nullable=False)
    rtsp_url = db.Column(db.Text, nullable=False)
    status = db.Column(db.Enum('Active', 'Inactive'), default='Active')
    view = db.Column(db.String(255), nullable=False)
    organization_id = db.Column(db.Integer, nullable=True, index=True)

    def __init__(self, camera_name, rtsp_url, view, status='Active', organization_id=None):
        self.camera_name = camera_name
        self.rtsp_url = rtsp_url
        self.status = status
        self.view = view
        self.organization_id = organization_id


class CameraSchema(ma.SQLAlchemyAutoSchema):
    class Meta:
        model = Camera

    rtsp_url = fields.Function(lambda obj: mask_credentials(obj.rtsp_url))

camera_schema = CameraSchema()
cameras_schema = CameraSchema(many=True)

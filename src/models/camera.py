from ..init import db, ma

class Camera(db.Model):
    __tablename__ = 'Camera'
    
    id = db.Column(db.Integer, primary_key=True)
    camera_name = db.Column(db.String(50), nullable=False)
    rtsp_url = db.Column(db.Text, nullable=False)
    status = db.Column(db.Enum('Active', 'Inactive'), default='Active')
    view = db.Column(db.String(255), nullable=False)

    def __init__(self, camera_name, rtsp_url, view, status='Active'):
        self.camera_name = camera_name
        self.rtsp_url = rtsp_url
        self.status = status
        self.view = view
        

class CameraSchema(ma.SQLAlchemyAutoSchema):
    class Meta:
        model = Camera

camera_schema = CameraSchema()
cameras_schema = CameraSchema(many=True)

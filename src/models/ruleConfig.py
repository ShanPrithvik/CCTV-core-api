from src.init import db, ma

class RuleConfig(db.Model):
    __tablename__ = 'RuleConfig'

    id = db.Column(db.Integer, primary_key=True)  
    camera_id = db.Column(db.Integer, db.ForeignKey('Camera.id'), nullable=False)
    model_type = db.Column(db.String(50), nullable=False) 
    roi_coordinates = db.Column(db.JSON, nullable=False)
    name = db.Column(db.String(255), nullable=False)  
    status = db.Column(db.Enum('Active', 'Inactive'), default='Active', nullable=False)
    task_id = db.Column(db.String(255), nullable=True)
    
    rule_types = db.relationship('RuleTypes', backref='ruleconfig', lazy=True)

    def __init__(self, camera_id, model_type, roi_coordinates, name):
        self.camera_id = camera_id
        self.model_type = model_type
        self.roi_coordinates = roi_coordinates
        self.name = name

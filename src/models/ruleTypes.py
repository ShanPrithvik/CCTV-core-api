from src.init import db

class RuleTypes(db.Model):
    __tablename__ = 'RuleTypes'
    id = db.Column(db.Integer, primary_key=True)  
    ruleconfig_id = db.Column(db.Integer, db.ForeignKey('RuleConfig.id'), nullable=False) 
    rule_type = db.Column(db.String(255), nullable=False) 
    rule_value = db.Column(db.String(255), nullable=False)
    
    def __init__(self, ruleconfig_id, rule_type, rule_value):
        self.ruleconfig_id = ruleconfig_id
        self.rule_type = rule_type
        self.rule_value = rule_value
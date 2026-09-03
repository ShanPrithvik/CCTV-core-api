from ..init import db, ma


class Organization(db.Model):
    __tablename__ = 'Organization'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    status = db.Column(db.Enum('Active', 'Inactive'), default='Active')


class OrganizationSchema(ma.SQLAlchemyAutoSchema):
    class Meta:
        model = Organization


organization_schema = OrganizationSchema()
organizations_schema = OrganizationSchema(many=True)

from ..init import db, ma


class Membership(db.Model):
    __tablename__ = 'Membership'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('User.id'), nullable=False)
    organization_id = db.Column(db.Integer, db.ForeignKey('Organization.id'), nullable=False)
    role = db.Column(db.Enum('Owner', 'Admin', 'Member'), default='Member')
    status = db.Column(db.Enum('Active', 'Inactive', 'Pending'), default='Active')
    invite_token = db.Column(db.String(255), nullable=True)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'organization_id', name='uq_user_org'),
    )


class MembershipSchema(ma.SQLAlchemyAutoSchema):
    class Meta:
        model = Membership


membership_schema = MembershipSchema()
memberships_schema = MembershipSchema(many=True)

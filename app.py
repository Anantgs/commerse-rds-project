import os
from decimal import Decimal

from flask import Flask, abort, flash, redirect, render_template, request, session, url_for
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import CheckConstraint, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


db = SQLAlchemy(model_class=Base)


# These models deliberately form four bounded modules. They can become separate
# catalog, inventory, cart, and order services without changing the web routes.
class Product(db.Model):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    inventory: Mapped["Inventory"] = relationship(back_populates="product", uselist=False)


class Inventory(db.Model):
    __tablename__ = "inventory"
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), primary_key=True)
    quantity: Mapped[int] = mapped_column(nullable=False, default=0)
    product: Mapped[Product] = relationship(back_populates="inventory")
    __table_args__ = (CheckConstraint("quantity >= 0", name="inventory_nonnegative"),)


class Order(db.Model):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    customer_email: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PLACED")
    total: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    items: Mapped[list["OrderItem"]] = relationship(back_populates="order", cascade="all, delete-orphan")


class OrderItem(db.Model):
    __tablename__ = "order_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    product_name: Mapped[str] = mapped_column(String(160), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    quantity: Mapped[int] = mapped_column(nullable=False)
    order: Mapped[Order] = relationship(back_populates="items")


def create_app():
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY", "local-development-only"),
        SQLALCHEMY_DATABASE_URI=os.environ.get("DATABASE_URL", "sqlite:///commerce.db"),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)

    @app.template_filter("currency")
    def currency(value):
        return f"${value:,.2f}"

    def cart_items():
        cart = session.get("cart", {})
        if not cart:
            return [], Decimal("0.00")
        products = db.session.scalars(db.select(Product).where(Product.id.in_(map(int, cart)))).all()
        rows = []
        total = Decimal("0.00")
        for product in products:
            quantity = int(cart[str(product.id)])
            subtotal = product.price * quantity
            rows.append((product, quantity, subtotal))
            total += subtotal
        return rows, total

    @app.get("/")
    def catalog():
        return render_template("catalog.html", products=db.session.scalars(db.select(Product).order_by(Product.id)).all())

    @app.post("/cart/<int:product_id>")
    def add_to_cart(product_id):
        product = db.get_or_404(Product, product_id)
        cart = session.get("cart", {})
        cart[str(product.id)] = min(int(cart.get(str(product.id), 0)) + 1, product.inventory.quantity)
        session["cart"] = cart
        flash(f"Added {product.name} to cart.")
        return redirect(url_for("catalog"))

    @app.get("/cart")
    def cart():
        items, total = cart_items()
        return render_template("cart.html", items=items, total=total)

    @app.post("/checkout")
    def checkout():
        email = request.form.get("email", "").strip()
        items, total = cart_items()
        if not email or not items:
            abort(400, "An email address and at least one cart item are required.")
        # Lock inventory rows while creating the order to prevent overselling.
        product_ids = [product.id for product, _, _ in items]
        locked = {item.product_id: item for item in db.session.scalars(db.select(Inventory).where(Inventory.product_id.in_(product_ids)).with_for_update())}
        for product, quantity, _ in items:
            if locked[product.id].quantity < quantity:
                db.session.rollback()
                abort(409, f"Insufficient stock for {product.name}.")
        order = Order(customer_email=email, total=total)
        db.session.add(order)
        for product, quantity, _ in items:
            locked[product.id].quantity -= quantity
            order.items.append(OrderItem(product_id=product.id, product_name=product.name, unit_price=product.price, quantity=quantity))
        db.session.commit()
        session.pop("cart", None)
        return render_template("confirmation.html", order=order)

    @app.cli.command("init-db")
    def init_db():
        db.create_all()
        if not db.session.scalar(db.select(Product).limit(1)):
            keyboard = Product(sku="KEY-001", name="Mechanical Keyboard", description="Compact hot-swappable keyboard", price=Decimal("89.99"))
            mouse = Product(sku="MSE-001", name="Wireless Mouse", description="Ergonomic wireless mouse", price=Decimal("34.99"))
            db.session.add_all([keyboard, mouse, Inventory(product=keyboard, quantity=20), Inventory(product=mouse, quantity=35)])
            db.session.commit()
        print("Database schema and sample catalog are ready.")

    return app


app = create_app()

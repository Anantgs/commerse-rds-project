# Monolithic commerce application with Amazon RDS

This is a small, deployable Flask commerce monolith. Product and stock data are read from an Amazon RDS for PostgreSQL instance; checkout writes orders and atomically reduces stock. It starts as one process and one RDS database, while its code and data ownership are separated for a later move to four microservices:

| Future service | Current tables / responsibility |
| --- | --- |
| Catalog | `products`; product browsing |
| Inventory | `inventory`; stock reservation and adjustment |
| Cart | Flask session cart; move it to Redis or a cart database later |
| Orders | `orders`, `order_items`; checkout and order history |

## 1. Create RDS

Create an RDS for PostgreSQL instance in the same VPC as the EC2 instance. Keep **Public access** disabled. Create database `commerce`, and create an RDS security-group inbound rule allowing TCP **5432** only from the EC2 application's security group. Never allow `0.0.0.0/0` to port 5432.

Connect as the RDS master user to the default `postgres` database, then create the application database and user. PostgreSQL does not use MySQL's `user@host` syntax or `FLUSH PRIVILEGES`:

```sql
CREATE DATABASE commerce;
CREATE USER commerce_user WITH LOGIN PASSWORD 'choose-a-long-unique-password';
GRANT CONNECT ON DATABASE commerce TO commerce_user;
\c commerce
GRANT USAGE, CREATE ON SCHEMA public TO commerce_user;
```

## 2. Deploy on Amazon Linux 2023 EC2

Launch EC2 in the same VPC. Its security group needs inbound HTTP (80) from your intended users and SSH (22) only from your IP. SSH in, then run:

```bash
sudo dnf update -y
sudo dnf install -y python3 python3-pip nginx git
sudo mkdir -p /opt/commerce
sudo chown ec2-user:ec2-user /opt/commerce
git clone <YOUR-REPOSITORY-URL> /opt/commerce
cd /opt/commerce/02-AWS-NOTES/RDS/Application
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
chmod 600 .env
nano .env
```

Set `DATABASE_URL` to your RDS endpoint and real credentials, keeping the PostgreSQL dialect prefix:

```text
DATABASE_URL=postgresql+psycopg://commerce_user:URL_ENCODED_PASSWORD@your-rds-endpoint:5432/commerce
```

If the password includes characters such as `@`, `:`, `/`, or `#`, URL-encode it. Initialise the database and test locally:

```bash
source .venv/bin/activate
flask --app app init-db
flask --app app run --host 0.0.0.0
```

Stop the development server with `Ctrl+C`, then install the production services:

```bash
sudo cp deploy/commerce.service /etc/systemd/system/commerce.service
sudo cp deploy/nginx.conf /etc/nginx/conf.d/commerce.conf
sudo nginx -t
sudo systemctl daemon-reload
sudo systemctl enable --now commerce nginx
sudo systemctl reload nginx
```

Open `http://<EC2-public-IP>/`, add products, and place an order. The catalog reads from RDS and the checkout transaction writes the order and inventory change to RDS.

## Operations and next evolution

Use `sudo journalctl -u commerce -f` for application logs and `sudo systemctl status commerce nginx` for health. Store production secrets in AWS Secrets Manager or SSM Parameter Store rather than leaving them in `.env` long term.

When splitting services, first extract Catalog as a read API, then Inventory with its own database and reservation API, then Orders. Publish an `OrderPlaced` event after checkout (using an outbox table) instead of having services directly update one another's database. This prevents the distributed monolith problem.

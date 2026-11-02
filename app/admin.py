import click
from flask.cli import with_appcontext
from werkzeug.security import generate_password_hash

from .extensions import mongo
from .utils import now


@click.command("create-admin")
@click.option("--email", prompt="E-mail do administrador")
@click.option("--name", prompt="Nome do administrador")
@click.password_option(prompt="Senha (mínimo de 8 caracteres)")
@with_appcontext
def create_admin(email, name, password):
    """Create a team administrator through trusted server access only."""
    email = email.strip().lower()
    name = name.strip()
    if not email or "@" not in email or not name or len(password) < 8:
        raise click.ClickException("Informe nome, e-mail válido e senha de pelo menos 8 caracteres.")
    if mongo.db.users.find_one({"email": email}):
        raise click.ClickException("Este e-mail já está cadastrado. Use um e-mail exclusivo para a administração.")
    timestamp = now()
    mongo.db.users.insert_one({
        "email": email,
        "name": name,
        "password_hash": generate_password_hash(password),
        "role": "admin",
        "organization_name": "",
        "headline": "Administração Return Tech",
        "city": "",
        "skills": [],
        "bio": "",
        "created_at": timestamp,
        "updated_at": timestamp,
    })
    click.echo("Administrador criado. Acesse /#/admin no frontend e entre com essa conta.")

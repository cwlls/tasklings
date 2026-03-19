"""
Placeholder index view -- replaced in later phases by the Runlist view.
"""
from quart import Blueprint, render_template

index_bp = Blueprint("index", __name__)


@index_bp.get("/")
async def index():
    return await render_template("index.html")

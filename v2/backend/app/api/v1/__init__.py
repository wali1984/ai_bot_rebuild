"""V1 router package.

Each module exports `router: APIRouter` with a §7-canonical prefix and an
OPTIONS shim returning the route group's metadata. Routers are registered
under `/api/v1` by `app.main.create_app()`.
"""

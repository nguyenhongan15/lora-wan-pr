"""Registry client: load active Stage 2 model on startup + hot-reload helpers.

Boundary giữa serving server và ml.* schema. Serving KHÔNG đụng SQL trực tiếp;
đi qua registry/client.py.
"""

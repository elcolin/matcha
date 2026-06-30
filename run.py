from app import create_app

app = create_app()

if __name__ == "__main__":
    # threaded=True is required: the chat page keeps a long-lived SSE
    # connection open (/chat/stream), and without threading the dev
    # server can only serve one request at a time, so every other page
    # would stall behind it for as long as the stream stays open.
    app.run(debug=True, threaded=True)
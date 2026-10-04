# Streamlit Client

The Streamlit app supports both batch result browsing and the conventional 2D live-study condition. It does not implement twin calculations: the live page reads `schema/twin_state_v1.json` from the Python server's `/ws` endpoint and posts participant responses to `/respond`.

After creating `.venv`, installing `requirements.txt`, and exporting the induction FMU, start the live server in one terminal:

```powershell
.\.venv\Scripts\python.exe -m server.live_server --host 127.0.0.1 --port 8000
```

Start Streamlit in another terminal:

```powershell
.\.venv\Scripts\python.exe -m streamlit run ui\app.py
```

Select **Live operator study** for the shared WebSocket state and `/respond` workflow. Select **Batch results** to launch experiments and inspect CSV outputs. The Unity/WebXR client must use the same server endpoint and payload contract for controlled comparisons.

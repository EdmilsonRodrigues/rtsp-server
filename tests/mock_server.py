from fastapi import FastAPI
from fastapi.responses import FileResponse

app = FastAPI()

@app.get("/cgi-bin/snapshot.cgi", response_class=FileResponse)
async def get_pic():
    return "test-pic.jpg"

if __name__ == '__main__':
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8082)

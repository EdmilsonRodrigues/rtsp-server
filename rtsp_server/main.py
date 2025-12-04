from typing import Annotated
from urllib.parse import urlparse

import cv2
import httpx
import numpy as np
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from pyzbar.pyzbar import decode

HOST = "127.0.0.1"
PORT = 8081
SNAPSHOT_URL = urlparse("http://ip/cgi-bin/snapshot.cgi?chn=1")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

async def get_client():
    async with httpx.AsyncClient() as client:
        yield client


class QrCodeResponse(BaseModel):
    alias: str
    qrcode: int = Field(alias="qrCode")


@app.get("/{ip}/snapshot", response_class=StreamingResponse)
async def get_snapshot(ip: str, client: Annotated[httpx.AsyncClient, Depends(get_client)]):
    url = SNAPSHOT_URL._replace(netloc=ip)

    async def stream_file():
        async with client.stream("GET", url.geturl()) as response:
            try:
                response.raise_for_status()
            except Exception as exc:
                raise HTTPException(500, f"Failed fetching stream: {str(exc)}") from exc

            async for chunk in response.aiter_bytes():
                yield chunk

    return StreamingResponse(stream_file(), media_type="image/jpeg", headers={"Content-Disposition": "attachment; filename=snapshot.jpg"})


@app.get("/{ip}/qrcode", response_model=QrCodeResponse)
async def read_qrcode(ip: str, client: Annotated[httpx.AsyncClient, Depends(get_client)]):
    url = SNAPSHOT_URL._replace(netloc=ip)

    response = await client.get(url.geturl())
    response.raise_for_status()

    image_array = np.asarray(bytearray(response.content), dtype=np.uint8)
    image = cv2.imdecode(image_array, cv2.IMREAD_COLOR)
    if image is None:
        raise HTTPException(500, "No Image Found")

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    decoded_objects = decode(gray)
    if len(decoded_objects) == 0:
        raise HTTPException(500, "No QR Code Found")
    alias, qr_code = decoded_objects[0].data.decode('utf-8').split('-')
    return QrCodeResponse(alias=alias, qrCode=qr_code)

if __name__ == '__main__':
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT)

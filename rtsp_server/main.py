from typing import Annotated
from urllib.parse import urlparse, ParseResult

import cv2
import httpx
import numpy as np
from fastapi import FastAPI, Depends, HTTPException, Path, Query
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from pydantic.networks import IPv4Address
from pyzbar.pyzbar import decode
from starlette.exceptions import HTTPException as StarletteHTTPException

HOST = "127.0.0.1"
PORT = 8081
SNAPSHOT_URL = urlparse("http://netloc/cgi-bin/snapshot.cgi?chn=1")
FLIP_CAMERA_URL = urlparse("http://netloc/cgi-bin/configManager.cgi?action=setConfig&VideoImageControl[0].Flip=true")
USERNAME = "admin"
PASSWORD = "Sea2025@"

class HTTPError(BaseModel):
    class Meta(BaseModel):
        code: int
        title: str
        message: str

    meta: Meta
    data: dict = {}

    @classmethod
    def new(cls, code: int, title: str, message: str):
        return jsonable_encoder(cls(meta=cls.Meta(code=code, title=title, message=message)))


class QrCodeResponse(BaseModel):
    alias: Annotated[str, Field()]
    qrcode: Annotated[int, Field(serialization_alias="qrCode")]

    
app = FastAPI()

@app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content=HTTPError.new(exc.status_code, "", str(exc))
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    return JSONResponse(
        status_code=422,
        content=HTTPError.new(422, "Invalid Request", ";".join(map(lambda err: err["msg"], exc.errors())))
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://admin-dev.sipub.com.br"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

async def get_client():
    async with httpx.AsyncClient(auth=httpx.DigestAuth(username=USERNAME, password=PASSWORD)) as client:
        yield client

def get_address(ip: Annotated[IPv4Address, Path()], port: Annotated[int | None, Query()] = None) -> str:
    if port:
        return ":".join(map(str, (ip, port)))
    return str(ip)

IP_Address = Annotated[str, Depends(get_address)]
HTTPClient = Annotated[httpx.AsyncClient, Depends(get_client)]

async def stream_file(client: httpx.AsyncClient, url: ParseResult):
    async with client.stream("GET", url.geturl()) as response:
        try:
            response.raise_for_status()
        except Exception as exc:
            raise HTTPException(response.status_code, f"Failed fetching stream: {str(exc)}") from exc

        async for chunk in response.aiter_bytes():
            yield chunk

def get_qr_code(content: bytes) -> QrCodeResponse:
    content = clean_jpeg_data(content)
    image_array = np.asarray(bytearray(content), dtype=np.uint8)
    image = cv2.imdecode(image_array, cv2.IMREAD_COLOR)
    if image is None:
        raise HTTPException(400, "No Image Found")

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    decoded_objects = decode(gray)
    if len(decoded_objects) == 0:
        raise HTTPException(500, "No QR Code Found")
    alias, qr_code = decoded_objects[0].data.decode('utf-8').split('-')
    return QrCodeResponse(alias=alias, qrcode=qr_code)

def clean_jpeg_data(data: bytes) -> bytes:
    """
    Clean JPEG data by finding the JPEG start (0xFFD8) and end (0xFFD9) markers.
    Removes any extraneous bytes before/after the JPEG image.
    """
    # Find JPEG start marker (0xFF 0xD8)
    start_marker = b'\xff\xd8'
    start_pos = data.find(start_marker)
    
    if start_pos == -1:
        # No JPEG marker found, return original
        return data
    
    # Find JPEG end marker (0xFF 0xD9)
    end_marker = b'\xff\xd9'
    end_pos = data.rfind(end_marker)
    
    if end_pos == -1:
        # No end marker found, try to decode anyway
        return data[start_pos:]
    
    # Return clean JPEG (from start marker to end marker + 2 bytes)
    return data[start_pos:end_pos + 2]

@app.get("/{ip}/snapshot", response_class=StreamingResponse)
async def get_snapshot(ip_address: IP_Address, client: HTTPClient):
    try:
        httpx.get(f"http://{ip_address}")
    except httpx.ConnectError as exc:
        raise HTTPException(500, "Failed connecting to server") from exc

    return StreamingResponse(
        stream_file(client, SNAPSHOT_URL._replace(netloc=ip_address)),
        media_type="image/jpeg",
        headers={"Content-Disposition": "attachment; filename=snapshot.jpeg"}
    )


@app.get("/{ip}/qrcode", response_model=QrCodeResponse)
async def read_qrcode(ip_address: IP_Address, client: HTTPClient):
    try:
        url = SNAPSHOT_URL._replace(netloc=ip_address)
        response = await client.get(url.geturl())
        response.raise_for_status()

        

        return get_qr_code(response.content)
    except httpx.ConnectError as exc:
        raise HTTPException(500, "Failed connecting to server") from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(response.status_code, str(exc)) from exc

@app.get("/{ip}/flip", response_model=QrCodeResponse)
async def flip_camera(ip_address: IP_Address, client: HTTPClient):
    try:
        url = FLIP_CAMERA_URL._replace(netloc=ip_address)
        response = await client.get(url.geturl())
        response.raise_for_status()

        return get_qr_code(response.content)
    except httpx.ConnectError as exc:
        raise HTTPException(500, "Failed connecting to server") from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(response.status_code, str(exc)) from exc

if __name__ == '__main__':
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT)

"""Bounded KTX1 decoder. NumPy is supplied by Blender; no downloads required."""
import struct
import zlib
import numpy as np

MAGIC = b'\xabKTX 11\xbb\r\n\x1a\n'
FORMATS = {0x8C4C: ('BC1-sRGB', 8, False, True),
           0x8C4D: ('BC1-sRGBA', 8, True, True),
           0x83F0: ('BC1-RGB', 8, False, False),
           0x83F1: ('BC1-RGBA', 8, True, False),
           0x8DBB: ('BC4-UNORM', 8, False, False),
           0x8DBD: ('BC5-UNORM', 16, False, False),
           0x83F3: ('BC3-RGBA', 16, True, False),
           0x8C4F: ('BC3-sRGBA', 16, True, True)}

def parse(raw):
    if len(raw)<64 or raw[:12]!=MAGIC:
        raise ValueError('Expected KTX1 magic')
    endian={b'\x01\x02\x03\x04':'<',b'\x04\x03\x02\x01':'>'}.get(raw[12:16])
    if not endian:
        raise ValueError('Invalid byte order')
    gltype,typesize,glformat,fmt,base,w,h,depth,arrays,faces,count,kvsize=struct.unpack(endian+'12I',raw[16:64])
    if fmt not in FORMATS or gltype!=0 or glformat!=0 or typesize!=1:
        raise ValueError('Unsupported encoding: only BC1/BC4 unsigned/BC5 unsigned')
    if depth!=0 or arrays!=0 or faces!=1 or not (1<=w<=16384 and 1<=h<=16384) or w*h>32_000_000:
        raise ValueError('Only bounded 2D non-array images supported')
    if count>max(w,h).bit_length() or kvsize>1024*1024 or 64+kvsize>len(raw):
        raise ValueError('Invalid mip count or metadata size')
    metadata,pos,end={},64,64+kvsize
    while pos<end:
        if pos+4>end:
            raise ValueError('Truncated metadata')
        n=struct.unpack_from(endian+'I',raw,pos)[0]
        pos+=4
        if n==0 or pos+n>end or b'\0' not in raw[pos:pos+n]:
            raise ValueError('Invalid metadata entry')
        key,value=raw[pos:pos+n].split(b'\0',1)
        metadata[key.decode('utf8')]=value
        pos+=(n+3)&~3
    if pos!=end:
        raise ValueError('Invalid metadata padding')
    levels=[]
    for level in range(max(1,count)):
        if pos+4>len(raw):
            raise ValueError('Truncated mip header')
        n=struct.unpack_from(endian+'I',raw,pos)[0]
        pos+=4
        mw,mh=max(1,w>>level),max(1,h>>level)
        if n!=((mw+3)//4)*((mh+3)//4)*FORMATS[fmt][1] or pos+n>len(raw):
            raise ValueError('Incorrect block payload length')
        levels.append(raw[pos:pos+n])
        pos+=(n+3)&~3
    if pos!=len(raw):
        raise ValueError('Unexpected trailing data')
    return dict(width=w,height=h,format=fmt,base=base,mips=len(levels),levels=levels,metadata=metadata)


def untile(pixels, w, h):
    channels = pixels.shape[2:]
    return pixels.reshape((h+3)//4, (w+3)//4, 4, 4, *channels).transpose(
        (0, 2, 1, 3) + tuple(range(4, 4+len(channels)))).reshape(
        ((h+3)//4*4, (w+3)//4*4) + channels)[:h, :w].copy()


def bc4(payload, w, h):
    blocks = np.frombuffer(payload, np.uint8).reshape(-1, 8).astype(np.uint64)
    a, b = blocks[:, 0], blocks[:, 1]
    table = np.empty((len(blocks), 8), np.uint64)
    table[:, 0], table[:, 1] = a, b
    for i in range(1, 7):
        table[:, i+1] = np.where(a > b, ((7-i)*a+i*b)//7,
                                ((5-i)*a+i*b)//5 if i < 5 else (0 if i == 5 else 255))
    bits = sum(blocks[:, i+2] << np.uint64(8*i) for i in range(6))
    indices = (bits[:, None] >> (np.arange(16, dtype=np.uint64)*3)) & 7
    return untile(np.take_along_axis(table, indices.astype(int), 1).astype(np.uint8), w, h)


def decode(info, normal=False, missing_orientation='S=r,T=d'):
    w, h, fmt = info['width'], info['height'], info['format']
    data = info['levels'][0]
    details = dict(format=FORMATS[fmt][0], width=w, height=h, mips_validated=info['mips'])
    if fmt in (0x8C4C, 0x8C4D, 0x83F0, 0x83F1, 0x83F3, 0x8C4F):
        bc3 = fmt in (0x83F3, 0x8C4F)
        if bc3:
            blocks = np.frombuffer(data, np.uint8).reshape(-1, 16)
            alpha = bc4(blocks[:, :8].copy().tobytes(), w, h)
            data = blocks[:, 8:].copy().tobytes()
        words = np.frombuffer(data, '<u2').reshape(-1, 4).astype(np.uint32)
        a, b = words[:, 0], words[:, 1]
        table = np.full((len(words), 4, 4), 255, np.uint32)
        for i, v in enumerate((a, b)):
            r, g, blue = (v >> 11) & 31, (v >> 5) & 63, v & 31
            table[:, i, :3] = np.stack(((r << 3) | (r >> 2), (g << 2) | (g >> 4), (blue << 3) | (blue >> 2)), 1)
        c0, c1 = table[:, 0, :3].copy(), table[:, 1, :3].copy()
        four = (a > b) | bc3
        table[:, 2, :3] = np.where(four[:, None], (2*c0+c1)//3, (c0+c1)//2)
        table[:, 3, :3] = np.where(four[:, None], (c0+2*c1)//3, 0)
        if FORMATS[fmt][2]:
            table[:, 3, 3] = np.where(a > b, 255, 0)
        bits = words[:, 2] | (words[:, 3] << 16)
        indices = (bits[:, None] >> (np.arange(16, dtype=np.uint32)*2)) & 3
        pixels = untile(table[np.arange(len(words))[:, None], indices].astype(np.uint8), w, h)
        if bc3:
            pixels[:, :, 3] = alpha
    elif fmt == 0x8DBB:
        pixels = bc4(data, w, h)
    else:
        blocks = np.frombuffer(data, np.uint8).reshape(-1, 16)
        r, g = (bc4(blocks[:, i:i+8].copy().tobytes(), w, h) for i in (0, 8))
        if normal:
            x, y = r.astype(float)/127.5-1, g.astype(float)/127.5-1
            radius = x*x+y*y
            scale = np.sqrt(np.maximum(radius, 1))
            x, y = x/scale, y/scale
            z = np.sqrt(np.maximum(0, 1-x*x-y*y))
            pixels = np.rint((np.stack((x, y, z), 2)+1)*127.5).clip(0, 255).astype(np.uint8)
            details.update(normal_z='positive hemisphere; out-of-disk XY projected', projected_pixels=int((radius > 1).sum()))
        else:
            pixels = np.stack((r, g, np.zeros_like(r)), 2)
            details['warning'] = 'BC5 two-channel data preserved; no normal semantic established'
    orientation = info['metadata'].get('KTXorientation', missing_orientation.encode()).rstrip(b'\0').decode()
    if orientation not in ('S=r,T=d', 'S=r,T=u'):
        raise ValueError('Unsupported orientation: '+orientation)
    if orientation == 'S=r,T=u':
        pixels = pixels[::-1].copy()
    details.update(orientation=orientation, orientation_is_assumption='KTXorientation' not in info['metadata'])
    return pixels, details


def png_bytes(pixels, srgb=False):
    h, w = pixels.shape[:2]
    channels = 1 if pixels.ndim == 2 else pixels.shape[2]
    color_type = {1: 0, 3: 2, 4: 6}[channels]
    def chunk(kind, payload):
        return struct.pack('>I', len(payload))+kind+payload+struct.pack('>I', zlib.crc32(kind+payload) & 0xffffffff)
    scan = np.zeros((h, w*channels+1), np.uint8)
    scan[:, 1:] = pixels.reshape(h, w*channels)
    return (b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR', struct.pack('>2I5B', w, h, 8, color_type, 0, 0, 0))
            +(chunk(b'sRGB', b'\0') if srgb else b'')
            +chunk(b'IDAT', zlib.compress(scan.tobytes(), 9))+chunk(b'IEND', b''))

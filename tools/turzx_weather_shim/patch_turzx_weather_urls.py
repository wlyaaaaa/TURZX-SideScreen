import argparse
from pathlib import Path


OLD_GEO = "https://mx2x86mrma.re.qweatherapi.com/geo/v2/city/lookup?location="
OLD_NOW = "https://mx2x86mrma.re.qweatherapi.com/v7/weather/now?location="
NEW_GEO = "http://127.0.0.1:18080/geo/v2/city/lookup?p=xxxxxxxxxxxx&location="
NEW_NOW = "http://127.0.0.1:18080/v7/weather/now?p=xxxxxxxxxxxx&location="
URL_SEED = 19


def encode_turzx_string(text, seed=URL_SEED):
    num = 2004917786 + seed + 14 + 89 + 89 + 65
    chars = []
    for char in text:
        code = ord(char)
        decoded_low = code & 0xFF
        decoded_high = (code >> 8) & 0xFF
        encoded_low = decoded_high ^ (num & 0xFF)
        num += 1
        encoded_high = decoded_low ^ (num & 0xFF)
        num += 1
        chars.append(chr((encoded_high << 8) | encoded_low))
    return "".join(chars)


def encoded_bytes(text):
    return encode_turzx_string(text).encode("utf-16le", "surrogatepass")


def patch_bytes(data, old_text, new_text):
    if len(old_text) != len(new_text):
        raise ValueError(f"Replacement length mismatch: {len(old_text)} != {len(new_text)}")

    old_bytes = encoded_bytes(old_text)
    new_bytes = encoded_bytes(new_text)
    offset = data.find(old_bytes)
    if offset < 0:
        raise ValueError(f"Could not find encoded URL: {old_text}")
    if data.find(old_bytes, offset + 1) >= 0:
        raise ValueError(f"Encoded URL appears more than once: {old_text}")

    data[offset : offset + len(old_bytes)] = new_bytes
    return offset


def patch_exe(exe_path, output_path):
    data = bytearray(exe_path.read_bytes())
    geo_offset = patch_bytes(data, OLD_GEO, NEW_GEO)
    now_offset = patch_bytes(data, OLD_NOW, NEW_NOW)
    output_path.write_bytes(data)
    return geo_offset, now_offset


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", default="TURZX.exe")
    parser.add_argument("--out", default="TURZX.weatherfix.exe")
    args = parser.parse_args()

    geo_offset, now_offset = patch_exe(Path(args.exe), Path(args.out))
    print(f"Patched geo URL at byte offset {geo_offset}")
    print(f"Patched now URL at byte offset {now_offset}")
    print(f"Output: {Path(args.out).resolve()}")


if __name__ == "__main__":
    main()

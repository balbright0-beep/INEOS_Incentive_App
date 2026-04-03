"""NHTSA VIN decoder integration."""

import httpx


async def decode_vin(vin: str) -> dict | None:
    """Decode a VIN using the NHTSA vPIC API. Returns vehicle info or None."""
    if not vin or len(vin) != 17:
        return None
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValues/{vin}",
                params={"format": "json"}
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            results = data.get("Results", [{}])[0]
            model_year = results.get("ModelYear", "")
            body_class = results.get("BodyClass", "")
            trim = results.get("Trim", "")
            msrp = results.get("BasePrice", "")

            # Map to our body styles
            body_style = "station_wagon"
            if "pickup" in body_class.lower() or "truck" in body_class.lower():
                body_style = "quartermaster"

            return {
                "vin": vin,
                "model_year": f"MY{model_year[-2:]}" if model_year else None,
                "body_style": body_style,
                "trim": trim or None,
                "msrp": float(msrp) if msrp and msrp != "0" else None,
                "raw": {
                    "make": results.get("Make", ""),
                    "model": results.get("Model", ""),
                    "body_class": body_class,
                },
            }
    except Exception:
        return None

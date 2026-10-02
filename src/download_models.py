"""
Run during Docker build to pre-download all supported models
into the depthai cache so no internet access is needed at runtime.
"""
import depthai as dai

MODELS = [
    "yolov6-nano",
    "luxonis/mobilenet-ssd:300x300",
]

print("Pre-downloading models for RVC2...")
for model_name in MODELS:
    try:
        desc = dai.NNModelDescription(model_name, platform="RVC2")
        path = dai.getModelFromZoo(desc, useCached=True)
        print(f"  OK: {model_name} -> {path}")
    except Exception as e:
        print(f"  WARN: {model_name} failed: {e}")

print("Done.")

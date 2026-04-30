from setuptools import Extension, setup

setup(
    name="catool_fast",
    version="1.0.0",
    description="Fast CPython extension helpers for CATool DSP/GCADPCM encode/decode",
    ext_modules=[
        Extension(
            "catool_fast",
            sources=["catool_fast.c"],
            extra_compile_args=["/O2"] if __import__("os").name == "nt" else ["-O3"],
        )
    ],
)

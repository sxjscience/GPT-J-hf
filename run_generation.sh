#!/bin/bash

set -ex

python3 generation_example.py \
    --output_dir ./ \
    --input "Why AutoGluon is great?" \
    --max_length 800 \
    --top_p 1.0 \
    --top_k 0 \
    --download_dir ./ \
    --seed 12345 \
    --dtype float16 | tee sample.txt

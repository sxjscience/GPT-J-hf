import time
import torch
from transformers import GPT2Tokenizer
from transformers.trainer_utils import set_seed
from modeling_gpt_neo import GPTNeoForCausalLM
import os
import logging
import hashlib
import requests
from tqdm import tqdm
import argparse


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
if (logger.hasHandlers()):
    logger.handlers.clear()
console = logging.StreamHandler()
logger.addHandler(console)


def download_ops(url, fname):
    dirname = os.path.dirname(os.path.abspath(os.path.expanduser(fname)))
    if not os.path.exists(dirname):
        os.makedirs(dirname)

    logger.info('Downloading %s from %s...'%(fname, url))
    r = requests.get(url, stream=True)
    if r.status_code != 200:
        raise RuntimeError("Failed downloading url %s"%url)
    total_length = r.headers.get('content-length')
    with open(fname, 'wb') as f:
        if total_length is None: # no content length header
            for chunk in r.iter_content(chunk_size=1024):
                if chunk: # filter out keep-alive new chunks
                    f.write(chunk)
        else:
            total_length = int(total_length)
            for chunk in tqdm(r.iter_content(chunk_size=1024),
                                total=int(total_length / 1024. + 0.5),
                                unit='KB', unit_scale=False, dynamic_ncols=True):
                f.write(chunk)

def download(url, path=None, overwrite=False, sha1_hash=None):
    """Download files from a given URL.
    """
    if path is None:
        fname = os.path.join(url.split('/')[-2],url.split('/')[-1])
    else:
        path = os.path.expanduser(path)
        if os.path.isdir(path):
            fname = os.path.join(path, url.split('/')[-2], url.split('/')[-1])
        else:
            fname = path
    if os.path.exists(fname) and sha1_hash:
        logger.info('File {} exist, checking content hash...'.format(fname))
        file_check = check_sha1(fname, sha1_hash)
        if file_check:
            logger.info('File {} checking pass'.format(fname))
        else:
            raise KeyError('File {} is downloaded but the content hash does not match. ' \
                                'Please retry.'.format(fname))

    elif overwrite or not os.path.exists(fname) :
        if overwrite:
            logger.info('File {} exist, overwriting...'.format(fname))
        download_ops(url,fname)
        if sha1_hash:
            logger.info('File {} downloaded, checking content hash...'.format(fname))
            file_check = check_sha1(fname, sha1_hash)
            if file_check:
                logger.info('File {} checking pass'.format(fname))
            else:
                raise KeyError('File {} is downloaded but the content hash does not match. ' \
                                    'Please retry.'.format(fname))
    return fname


def check_sha1(filename, sha1_hash):
    """Check whether the sha1 hash of the file content matches the expected hash.
    """
    sha1 = hashlib.sha1()
    with open(filename, 'rb') as f:
        while True:
            data = f.read(1048576)
            if not data:
                break
            sha1.update(data)

    return sha1.hexdigest() == sha1_hash


def add_args(parser: argparse.ArgumentParser):
    parser.add_argument('--output_dir', type=str, default='./',
                        help='output dir')
    parser.add_argument('--input', type=str, default='Why AutoGluon is great?',
                        help='input text')
    parser.add_argument('--max_length', type=int, default=800,
                        help='max length of generation example')
    parser.add_argument('--top_p', type=float, default=0.9,
                        help='top-p value in the sampler.')
    parser.add_argument('--top_k', type=int, default=0,
                        help='top-k value in the sampler.')
    parser.add_argument('--download_dir', type=str, default=None,
                        help='Destination path to store downloaded file, default in current dir')
    parser.add_argument('--dtype', type=str, choices=['float16', 'bfloat16'])
    parser.add_argument('--seed', type=int, default=None,
                        help='The seed for generating the samples.')


def main():
    torch.set_grad_enabled(False)  # we don't need gradients since we're just running inference
    parser = argparse.ArgumentParser()
    add_args(parser)
    args = parser.parse_args()
    if args.seed is not None:
        set_seed(args.seed)

    urls = {
        'config.json': {
            'url': 'https://zhisu-nlp.s3.us-west-2.amazonaws.com/gpt-j-hf/config.json',
            'sha1sum': 'a0af27bcff3c0fa17ec9718ffb6060b8db5e54e4'
        },
        'pytorch_model.bin': {
            'url': 'https://zhisu-nlp.s3.us-west-2.amazonaws.com/gpt-j-hf/pytorch_model.bin',
            'sha1sum': 'bab870fc9b82f0bfb3f6cbf4bd6bec3f3add05a6'
        }
    }

    for file_name, info in urls.items():
        download(info['url'], args.download_dir, sha1_hash=info['sha1sum'])

    logger.info("***download finished***")
    logger.info("***loading model***")
    # Load the model with bfloat16 to save memory
    start = time.time()
    torch.set_default_dtype(torch.bfloat16)
    model = GPTNeoForCausalLM.from_pretrained("./gpt-j-hf")
    torch.set_default_dtype(torch.float32)
    end = time.time()
    logger.info(f"***loading finished. Time spent={end - start}s.***")
    model.eval()

    tokenizer = GPT2Tokenizer.from_pretrained('gpt2')
    if args.dtype == 'float16':
        model.to(dtype=torch.float16, device=torch.device('cuda:0'))
    elif args.dtype == 'bfloat16':
        model.to(dtype=torch.bfloat16, device=torch.device('cuda:0'))
    else:
        raise NotImplementedError
    input_text = args.input
    logger.info("***encoding***")
    start = time.time()
    input_ids = tokenizer.encode(str(input_text), return_tensors='pt').cuda()
    logger.info("***generating***")
    output = model.generate(
        input_ids,
        do_sample=True,
        max_length=args.max_length,
        top_p=args.top_p,
        top_k=args.top_k,
        temperature=1.0,
    )
    output_context = tokenizer.decode(output[0], skip_special_tokens=True)
    end = time.time()
    logger.info('***output_context: {}'.format(output_context))
    logger.info(f'Total time spent: {end - start}s.')
    output_file = os.path.join(args.output_dir,'output_context.txt')
    with open(output_file, "w", encoding='utf-8') as f:
        f.write(str(output_context))
    logger.info("***output has been saved to {}***".format(output_file))
    logger.info("***finished***")


if __name__ == '__main__':
    main()

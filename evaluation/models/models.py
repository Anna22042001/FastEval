import os
import threading

import evaluation.utils

fetched_model_configs = {}
fetched_model_configs_lock = threading.Lock()


def fetch_model_config(model_name: str):
    fetched_model_configs_lock.acquire()

    if model_name in fetched_model_configs:
        model_config = fetched_model_configs[model_name]
        fetched_model_configs_lock.release()
        return model_config

    import transformers

    model_config = transformers.AutoConfig.from_pretrained(
        model_name, trust_remote_code=True
    )
    fetched_model_configs[model_name] = model_config

    fetched_model_configs_lock.release()

    return model_config


def get_dtype(model_name: str):
    return fetch_model_config(model_name).torch_dtype


def get_supported_inference_backends(model_name: str):
    if "starchat" in model_name:
        # vLLM currently does not support starchat.
        # See https://github.com/vllm-project/vllm/issues/380
        return ["tgi", "hf_transformers"]

    generally_supported_model_types = [
        "llama",  # LLaMA & LLaMA-2
        "gpt_neox",  # EleutherAI Pythia models
        "gpt_bigcode",  # Starcoder
        "mpt",  # MPT models from MosaicML
        # All of these are some variant of falcon from TII
        "RefinedWeb",
        "RefinedWebModel",
        "falcon",
    ]

    model_type = fetch_model_config(model_name).model_type
    if model_type in generally_supported_model_types:
        return ["vllm", "tgi", "hf_transformers"]

    return []


def is_tgi_installed():
    return os.path.exists("text-generation-inference")


def get_inference_backend(model_path: str):
    supported_backends = get_supported_inference_backends(model_path)

    if "vllm" in supported_backends:
        return "vllm"

    if "tgi" in supported_backends:
        if is_tgi_installed():
            return "tgi"
        print(
            'WARNING: The model "'
            + model_path
            + '" can be greatly accelerated by text-generation-inference, but it is not installed.'
        )

    if "hf_transformers" in supported_backends:
        return "hf_transformers"

    raise Exception('No inference backend supported for model "' + model_path)


def create_model(
    model_type: str, model_name: str, model_args: dict[str, str], **kwargs
):
    from evaluation.models.alpaca_with_prefix import AlpacaWithPrefix
    from evaluation.models.alpaca_without_prefix import AlpacaWithoutPrefix
    from evaluation.models.chatml import ChatML
    from evaluation.models.debug import Debug
    from evaluation.models.dolphin import Dolphin
    from evaluation.models.falcon_instruct import FalconInstruct
    from evaluation.models.fastchat import Fastchat
    from evaluation.models.guanaco import Guanaco
    from evaluation.models.llama2_chat import Llama2Chat
    from evaluation.models.open_ai import OpenAI
    from evaluation.models.open_assistant import OpenAssistant
    from evaluation.models.openchat_llama2_v1 import OpenchatLlama2V1
    from evaluation.models.stable_beluga import StableBeluga
    from evaluation.models.starchat import Starchat
    from evaluation.models.wizard_lm import WizardLM

    model_classes = {
        "debug": Debug,
        "openai": OpenAI,
        "fastchat": Fastchat,
        "open-assistant": OpenAssistant,
        "guanaco": Guanaco,
        "falcon-instruct": FalconInstruct,
        "alpaca-without-prefix": AlpacaWithoutPrefix,
        "alpaca-with-prefix": AlpacaWithPrefix,
        "chatml": ChatML,
        "starchat": Starchat,
        "llama2-chat": Llama2Chat,
        "stable-beluga": StableBeluga,
        "dolphin": Dolphin,
        "openchat-llama2-v1": OpenchatLlama2V1,
        "wizard-lm": WizardLM,
    }

    if model_type not in model_classes:
        raise Exception('Unknown model type "' + model_type + '"')

    model_class = model_classes[model_type]

    return model_class(model_name, **model_args, **kwargs)


def compute_model_replies(model, conversations, *, progress_bar_description=None):
    if len(conversations) == 0:
        return []

    def compute_reply(conversation, *, stop_event):
        if isinstance(conversation, list):
            return model.reply(conversation, stop_event=stop_event)
        elif isinstance(conversation, dict):
            return model.reply(**conversation, stop_event=stop_event)
        raise

    return evaluation.utils.process_with_thread_pool(
        num_threads=model.num_threads,
        items=conversations,
        process_fn=compute_reply,
        progress_bar_description=progress_bar_description,
        use_stop_event=True,
    )


def switch_inference_backend(new_inference_backend):
    import evaluation.models.fastchat
    import evaluation.models.huggingface_backends.hf_transformers
    import evaluation.models.huggingface_backends.tgi
    import evaluation.models.huggingface_backends.vllm_backend

    unload_backend_fns = {
        "hf_transformers": evaluation.models.huggingface_backends.hf_transformers.unload_model,
        "vllm": evaluation.models.huggingface_backends.vllm_backend.unload_model,
        "tgi": evaluation.models.huggingface_backends.tgi.unload_model,
        "fastchat": evaluation.models.fastchat.unload_model,
    }

    for inference_backend_name, unload_backend_fn in unload_backend_fns.items():
        if inference_backend_name == new_inference_backend:
            continue
        unload_backend_fn()


def unload_model():
    switch_inference_backend(None)

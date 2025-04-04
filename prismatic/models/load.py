"""
load.py

Entry point for loading pretrained VLMs for inference; exposes functions for listing available models (with canonical
IDs, mappings to paper experiments, and short descriptions), as well as for loading models (from disk or HF Hub).
"""

import json
import os
from pathlib import Path
from typing import List, Optional, Union

from huggingface_hub import hf_hub_download

from prismatic.models.materialize import get_llm_backbone_and_tokenizer, get_vision_backbone_and_transform
from prismatic.models.registry import GLOBAL_REGISTRY, MODEL_REGISTRY
from prismatic.models.vlms import PrismaticVLM
from prismatic.overwatch import initialize_overwatch

# Initialize Overwatch =>> Wraps `logging.Logger`
overwatch = initialize_overwatch(__name__)


# === HF Hub Repository ===
HF_HUB_REPO = "TRI-ML/prismatic-vlms"


# === Available Models ===
def available_model_ids() -> List[str]:
    return list(MODEL_REGISTRY.keys())


def available_model_ids_and_names() -> List[List[str]]:
    return list(GLOBAL_REGISTRY.values())


def get_model_description(model_id_or_name: str) -> str:
    if model_id_or_name not in GLOBAL_REGISTRY:
        raise ValueError(f"Couldn't find `{model_id_or_name = }; check `prismatic.available_model_names()`")

    # Print Description & Return
    print(json.dumps(description := GLOBAL_REGISTRY[model_id_or_name]["description"], indent=2))

    return description


# === Load Pretrained Model ===
def load(
    model_id_or_path: Union[str, Path], hf_token: Optional[str] = None, cache_dir: Optional[Union[str, Path]] = None
) -> PrismaticVLM:
    
    rylan_trained_models = {
            "prism-gemma-instruct+2b+clip",
            "prism-gemma-instruct+2b+siglip",
            "prism-gemma-instruct+2b+dinosiglip",
            "prism-gemma-instruct+8b+clip",
            "prism-gemma-instruct+8b+siglip",
            "prism-gemma-instruct+8b+dinosiglip",
            "prism-llama2-chat+7b+clip",
            "prism-llama2-chat+7b+siglip",
            "prism-llama2-chat+7b+dinosiglip",
            "prism-llama3-instruct+8b+clip",
            "prism-llama3-instruct+8b+siglip",
            "prism-llama3-instruct+8b+dinosiglip",
            "prism-mistral-instruct-v0.2+7b+clip",
            "prism-mistral-instruct-v0.2+7b+siglip",
            "prism-mistral-instruct-v0.2+7b+dinosiglip",
            "prism-phi-instruct-3+4b+clip",
            "prism-phi-instruct-3+4b+siglip",
            "prism-phi-instruct-3+4b+dinosiglip",
        }
    
    """Loads a pretrained PrismaticVLM from either local disk or the HuggingFace Hub."""
    
    # ISHA FIX: it never recognized the local mode...
    
    # if model_id_or_path in GLOBAL_REGISTRY:
    #     full_path = "../models--TRI-ML--prismatic-vlms/snapshots/a3ba8a19c453a82eaf5a3fb1e699dd9e441f0a12/" + model_id_or_path
    # elif model_id_or_path in rylan_trained_models:
    #     full_path = "../models--RylanSchaeffer--prismatic-vlms/snapshots/60c88dda2e826a3ff569546205e4b51621007e1e/" + model_id_or_path.removeprefix("prism-")
        
    full_path = model_id_or_path
    print(full_path)
    if os.path.isdir(full_path):
        overwatch.info(f"Loading from local path `{(run_dir := Path(full_path))}`")
        # Get paths for `config.json` and pretrained checkpoint
        config_json, checkpoint_pt = run_dir / "config.json", run_dir / "checkpoints" / "latest-checkpoint.pt"
        assert config_json.exists(), f"Missing `config.json` for `{run_dir = }`"
        assert checkpoint_pt.exists(), f"Missing checkpoint for `{run_dir = }`"
    else:
        if (model_id_or_path not in rylan_trained_models) and (model_id_or_path not in GLOBAL_REGISTRY):
            raise ValueError(f"Couldn't find `{model_id_or_path = }; check `prismatic.available_model_names()`")

        if model_id_or_path in rylan_trained_models:
            repo_id = "RylanSchaeffer/prismatic-vlms"
            model_id = model_id_or_path.replace("prism-", "")
        else:
            repo_id = "TRI-ML/prismatic-vlms"
            model_id = GLOBAL_REGISTRY[model_id_or_path]['model_id']

        overwatch.info(f"Downloading `{model_id} from HF Hub")
        config_json = hf_hub_download(repo_id=repo_id, filename=f"{model_id}/config.json", cache_dir=cache_dir)
        checkpoint_pt = hf_hub_download(
            repo_id=repo_id, filename=f"{model_id}/checkpoints/latest-checkpoint.pt", cache_dir=cache_dir
        )

    # Load Model Config from `config.json`
    with open(config_json, "r") as f:
        model_cfg = json.load(f)["model"]

    # = Load Individual Components necessary for Instantiating a VLM =
    #   =>> Print Minimal Config
    overwatch.info(
        f"Found Config =>> Loading & Freezing [bold blue]{model_cfg['model_id']}[/] with:\n"
        f"             Vision Backbone =>> [bold]{model_cfg['vision_backbone_id']}[/]\n"
        f"             LLM Backbone    =>> [bold]{model_cfg['llm_backbone_id']}[/]\n"
        f"             Arch Specifier  =>> [bold]{model_cfg['arch_specifier']}[/]\n"
        f"             Checkpoint Path =>> [underline]`{checkpoint_pt}`[/]"
    )

    # Load Vision Backbone
    overwatch.info(f"Loading Vision Backbone [bold]{model_cfg['vision_backbone_id']}[/]")
    vision_backbone, image_transform = get_vision_backbone_and_transform(
        model_cfg["vision_backbone_id"],
        model_cfg["image_resize_strategy"],
    )

    # Load LLM Backbone --> note `inference_mode = True` by default when calling `load()`
    overwatch.info(f"Loading Pretrained LLM [bold]{model_cfg['llm_backbone_id']}[/] via HF Transformers")
    llm_backbone, tokenizer = get_llm_backbone_and_tokenizer(
        model_cfg["llm_backbone_id"],
        llm_max_length=model_cfg.get("llm_max_length", 2048),
        hf_token=hf_token,
        inference_mode=True,
    )

    # Load VLM using `from_pretrained` (clobbers HF syntax... eventually should reconcile)
    overwatch.info(f"Loading VLM [bold blue]{model_cfg['model_id']}[/] from Checkpoint; Freezing Weights 🥶")
    vlm = PrismaticVLM.from_pretrained(
        checkpoint_pt,
        model_cfg["model_id"],
        vision_backbone,
        llm_backbone,
        arch_specifier=model_cfg["arch_specifier"]
    )

    return vlm, tokenizer

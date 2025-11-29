import json
import logging
import argparse
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class ConfigManager:
    """
    Manages configuration loading from JSON files and CLI arguments.
    Prioritizes CLI arguments over JSON config values.
    """

    @staticmethod
    def load_config(config_path: str) -> Dict[str, Any]:
        """Load configuration from a JSON file."""
        path = Path(config_path)
        if not path.exists():
            logger.warning(f"Config file not found: {config_path}")
            return {}
        
        try:
            with open(path, 'r') as f:
                config = json.load(f)
                logger.info(f"Loaded configuration from {config_path}")
                return config
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing config file {config_path}: {e}")
            return {}
        except Exception as e:
            logger.error(f"Error loading config file {config_path}: {e}")
            return {}

    @staticmethod
    def merge_args_with_config(args: argparse.Namespace, config: Dict[str, Any]) -> argparse.Namespace:
        """
        Merge CLI arguments with configuration file values.
        CLI arguments take precedence if they are not their default values (if we could track that),
        but typically we want config file to provide defaults for CLI args.
        
        However, standard pattern is: CLI args > Config File > Defaults.
        
        Since argparse applies defaults immediately, it's hard to know if a value was user-supplied or default.
        A common workaround is to check if the value in args is different from the default, OR
        we can update the args namespace with config values ONLY if the arg value is None or default.
        
        Simpler approach for this implementation:
        1. Load config.
        2. If a key in config matches an arg name, and the arg wasn't explicitly set by user (hard to detect without complex logic),
           we might overwrite.
           
        Better approach:
        We will assume that if a config file is provided, its values should override the *defaults* of the CLI,
        but explicit CLI args should override the config file.
        
        To do this effectively with argparse, we can:
        1. Parse args to get the config path.
        2. Load config.
        3. Set defaults of the parser using the loaded config.
        4. Re-parse args.
        """
        # This method is a helper if we want to manually merge, but the re-parsing strategy is cleaner.
        # We'll leave this for manual merging if needed.
        
        arg_dict = vars(args)
        for key, value in config.items():
            # Convert config keys to match argparse dest (usually snake_case)
            key = key.replace('-', '_')
            if key in arg_dict:
                # Here we have a dilemma: we don't know if arg_dict[key] is a user input or a default.
                # So we'll trust the caller to handle the priority or use the re-parsing strategy in main.
                pass
        return args

    @staticmethod
    def setup_parser_with_config(parser: argparse.ArgumentParser, cli_args: Optional[List[str]] = None) -> argparse.Namespace:
        """
        Parse arguments supporting a configuration file.
        1. Parse only known args to find --config
        2. Load config file
        3. Update parser defaults with config values
        4. Parse all args
        """
        # First pass: look for config file
        temp_parser = argparse.ArgumentParser(add_help=False)
        temp_parser.add_argument('--config', help='Path to JSON configuration file')
        known_args, _ = temp_parser.parse_known_args(cli_args)

        if known_args.config:
            config = ConfigManager.load_config(known_args.config)
            
            # Normalize config keys to match argparse dest
            # e.g. "input-file" -> "input_file"
            normalized_config = {}
            for k, v in config.items():
                normalized_config[k.replace('-', '_')] = v
                
            parser.set_defaults(**normalized_config)

        # Second pass: parse everything
        return parser.parse_args(cli_args)

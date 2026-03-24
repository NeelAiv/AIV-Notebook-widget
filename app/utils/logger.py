import logging
import sys

# Configure the logger
style = "[%(levelname)s] InsightEdgeAI: %(message)s"
logging.basicConfig(
    level=logging.INFO,
    format=style,
    handlers=[logging.StreamHandler(sys.stdout)]
)

logger = logging.getLogger("InsightEdgeAI")

def info(msg):
    logger.info(msg)

def error(msg):
    logger.error(msg)

def warning(msg):
    logger.warning(msg)

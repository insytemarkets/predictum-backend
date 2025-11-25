import logging

logger = logging.getLogger(__name__)

def normalize_market_data(raw_data):
    """
    Normalize market data from Gamma API to internal schema.
    """
    try:
        # Example transformation
        return {
            "condition_id": raw_data.get("conditionId"),
            "question": raw_data.get("question"),
            "slug": raw_data.get("slug"),
            "url": f"https://polymarket.com/event/{raw_data.get('slug')}",
            "end_date": raw_data.get("endDate"),
            "volume_24h": raw_data.get("volume24hr"),
            "liquidity": raw_data.get("liquidity"),
            "raw_data": raw_data
        }
    except Exception as e:
        logger.error(f"Error normalizing data: {e}")
        return None


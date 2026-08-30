"""
Anime Mirchi Web Scraper Service
Fetches and parses Hindi-dubbed anime information from Anime Mirchi website
"""

import requests
from bs4 import BeautifulSoup
from typing import Optional, Dict, List
import time

from config import (
    ANIME_MIRCHI_BASE_URL,
    ANIME_MIRCHI_SEARCH_URL,
    REQUEST_TIMEOUT,
    MAX_RETRIES,
    RETRY_DELAY
)
from utils.logger import logger


class AnimeScraper:
    """Scrapes anime information from Anime Mirchi website"""

    def __init__(self):
        self.base_url = ANIME_MIRCHI_BASE_URL
        self.search_url = ANIME_MIRCHI_SEARCH_URL
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                         'AppleWebKit/537.36 (KHTML, like Gecko) '
                         'Chrome/120.0.0.0 Safari/537.36'
        })

    def search_anime(self, anime_name: str) -> Optional[Dict]:
        """
        Search for anime by name on Anime Mirchi
        
        Args:
            anime_name: Name of the anime to search for
            
        Returns:
            Dictionary with anime information or None if not found
        """
        if not anime_name or not anime_name.strip():
            logger.warning("Empty anime name provided")
            return None

        anime_name = anime_name.strip()
        logger.info(f"Searching for anime: {anime_name}")

        try:
            # Try to fetch anime information with retry logic
            anime_info = self._fetch_with_retry(anime_name)
            
            if anime_info:
                logger.info(f"Successfully found anime: {anime_name}")
                return anime_info
            else:
                logger.info(f"Anime not found: {anime_name}")
                return None
                
        except Exception as e:
            logger.error(f"Error searching for anime '{anime_name}': {str(e)}")
            return None

    def _fetch_with_retry(self, anime_name: str, attempt: int = 0) -> Optional[Dict]:
        """
        Fetch anime information with retry logic
        
        Args:
            anime_name: Name of anime to fetch
            attempt: Current attempt number
            
        Returns:
            Dictionary with anime info or None
        """
        try:
            # Construct search URL with anime name as parameter
            # Anime Mirchi uses search functionality
            search_params = {'s': anime_name}
            
            response = self.session.get(
                self.search_url,
                params=search_params,
                timeout=REQUEST_TIMEOUT
            )
            response.raise_for_status()
            
            # Parse and extract anime information
            anime_info = self._parse_search_results(response.text, anime_name)
            return anime_info
            
        except requests.exceptions.Timeout:
            logger.warning(f"Request timeout for anime: {anime_name} (Attempt {attempt + 1}/{MAX_RETRIES + 1})")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)
                return self._fetch_with_retry(anime_name, attempt + 1)
            return None
            
        except requests.exceptions.ConnectionError:
            logger.warning(f"Connection error for anime: {anime_name} (Attempt {attempt + 1}/{MAX_RETRIES + 1})")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)
                return self._fetch_with_retry(anime_name, attempt + 1)
            return None
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Request error: {str(e)}")
            return None

    def _parse_search_results(self, html_content: str, anime_name: str) -> Optional[Dict]:
        """
        Parse search results HTML and extract anime information
        
        Args:
            html_content: HTML content from Anime Mirchi
            anime_name: Original search term
            
        Returns:
            Dictionary with parsed anime information or None
        """
        try:
            # Use lxml parser for better HTML parsing
            soup = BeautifulSoup(html_content, 'lxml')
            
            # Look for article/post containers that match the anime name
            articles = soup.find_all(['article', 'div'], class_=lambda x: x and 'post' in x.lower())
            
            if not articles:
                logger.debug(f"No article elements found for: {anime_name}")
                return None
            
            for article in articles:
                # Extract title
                title_elem = article.find(['h1', 'h2', 'h3', 'a'])
                if not title_elem:
                    continue
                    
                title = title_elem.get_text(strip=True)
                
                if not title:
                    continue
                
                # Check if title matches the search term (loose matching)
                if self._is_matching_title(title, anime_name):
                    # Extract link
                    link_elem = article.find('a', href=True)
                    link = link_elem.get('href') if link_elem else None
                    
                    # Extract content for Hindi dub and platform info
                    content = article.get_text(strip=True)
                    
                    anime_info = {
                        'name': title,
                        'hindi_dub': self._extract_hindi_dub_status(content),
                        'platform': self._extract_platform(content),
                        'english_dub': self._extract_english_dub_status(content),
                        'source_link': link
                    }
                    
                    logger.debug(f"Found anime: {title} with dub: {anime_info['hindi_dub']}")
                    return anime_info
            
            logger.debug(f"No matching results found for: {anime_name}")
            return None
            
        except Exception as e:
            logger.error(f"Error parsing search results: {str(e)}")
            return None

    @staticmethod
    def _is_matching_title(title: str, search_term: str) -> bool:
        """
        Check if title matches search term (case-insensitive, partial match)
        
        Args:
            title: Title from search results
            search_term: Original search term
            
        Returns:
            True if titles match
        """
        if not title or not search_term:
            return False
            
        title_lower = title.lower().strip()
        search_lower = search_term.lower().strip()
        
        # Exact or partial match
        return (search_lower in title_lower or 
                title_lower.startswith(search_lower) or
                all(word in title_lower for word in search_lower.split() if word))

    @staticmethod
    def _extract_hindi_dub_status(content: str) -> str:
        """
        Extract Hindi dub availability status from content
        
        Args:
            content: Article content
            
        Returns:
            "Available" or "Not Available" or "Status Unknown"
        """
        if not content:
            return "Status Unknown"
            
        content_lower = content.lower()
        
        # Check for Hindi dub indicators
        hindi_indicators = ['hindi dub', 'hindi dubbed', 'hindi version', 'hindi audio']
        not_available_indicators = ['not available', 'unavailable', 'no hindi', 'without hindi', 'hindi dub not available']
        
        # Check for negative indicators first
        for indicator in not_available_indicators:
            if indicator in content_lower:
                logger.debug(f"Found negative indicator: {indicator}")
                return "Not Available"
        
        # Check for positive indicators
        for indicator in hindi_indicators:
            if indicator in content_lower:
                logger.debug(f"Found positive indicator: {indicator}")
                return "Available"
        
        # Default: Unknown/Not mentioned
        return "Status Unknown"

    @staticmethod
    def _extract_platform(content: str) -> Optional[str]:
        """
        Extract platform information from content
        
        Args:
            content: Article content
            
        Returns:
            Platform name or None
        """
        if not content:
            return None
            
        content_lower = content.lower()
        
        platforms = {
            'Netflix': ['netflix'],
            'Amazon Prime Video': ['amazon prime', 'prime video'],
            'Crunchyroll': ['crunchyroll'],
            'Disney+': ['disney+', 'disney plus'],
            'Disney Hotstar': ['hotstar', 'disney hotstar'],
            'MX Player': ['mx player'],
            'ZEE5': ['zee5'],
            'SonyLiv': ['sony liv', 'sonyliv'],
        }
        
        for platform, keywords in platforms.items():
            for keyword in keywords:
                if keyword in content_lower:
                    logger.debug(f"Found platform: {platform}")
                    return platform
        
        return None

    @staticmethod
    def _extract_english_dub_status(content: str) -> Optional[str]:
        """
        Extract English dub availability from content
        
        Args:
            content: Article content
            
        Returns:
            "Available" or "Not Available" or None (if not mentioned)
        """
        if not content:
            return None
            
        content_lower = content.lower()
        
        # Look for English dub information
        if 'english dub' in content_lower or 'english dubbed' in content_lower:
            if 'not available' not in content_lower and 'unavailable' not in content_lower:
                logger.debug("Found English dub available")
                return "Available"
            else:
                logger.debug("Found English dub not available")
                return "Not Available"
        
        # If not mentioned, return None
        return None


# Create a singleton instance
anime_scraper = AnimeScraper()


def get_anime_info(anime_name: str) -> Optional[Dict]:
    """
    Convenience function to get anime information
    
    Args:
        anime_name: Name of the anime to search for
        
    Returns:
        Dictionary with anime information or None
    """
    return anime_scraper.search_anime(anime_name)

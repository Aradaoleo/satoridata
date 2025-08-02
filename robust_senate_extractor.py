# Enhanced version of robust_senate_extractor.py with improved error handling
import json
import os
import time
import re
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
import requests
from urllib.parse import urljoin
import logging
from datetime import datetime

# Configure detailed logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('senate_scraper.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class EnhancedSenateExtractor:
    def __init__(self):
        self.driver = None
        self.session = requests.Session()
        self.base_url = "https://efdsearch.senate.gov"
        self.setup_driver()
        
    def setup_driver(self):
        """Setup Chrome driver with enhanced options"""
        options = Options()
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--headless")
        options.add_argument("--user-data-dir=C:\\EMPIRE\\SATORI_Scraper\\chrome_profile")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-plugins")
        options.add_argument("--disable-images")  # Speed up loading
        options.add_argument("--disable-javascript")  # Try without JS for some cases
        self.driver = webdriver.Chrome(options=options)
        
    def establish_session(self):
        """Establish session with multiple fallback strategies"""
        logger.info("Establishing session with Senate website...")
        
        # Strategy 1: Standard Selenium approach
        try:
            self.driver.get(f"{self.base_url}/search/")
            time.sleep(2)
            
            # Accept agreement
            agreement_checkbox = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.ID, "agree_statement"))
            )
            agreement_checkbox.click()
            logger.info("Accepted agreement via Selenium")
            
            # Transfer cookies to requests session
            for cookie in self.driver.get_cookies():
                self.session.cookies.set(cookie['name'], cookie['value'])
            
            return True
        except Exception as e:
            logger.warning(f"Selenium session establishment failed: {e}")
        
        # Strategy 2: Direct requests approach
        try:
            logger.info("Trying direct requests approach...")
            response = self.session.get(f"{self.base_url}/search/")
            if "agree_statement" in response.text:
                # Find agreement form and submit
                soup = BeautifulSoup(response.text, 'html.parser')
                agreement_form = soup.find('form', {'id': 'agreement_form'})
                if agreement_form:
                    action = agreement_form.get('action')
                    if action:
                        response = self.session.post(
                            urljoin(self.base_url, action),
                            data={'agree_statement': 'agree'}
                        )
                        if response.status_code == 200:
                            logger.info("Accepted agreement via requests")
                            return True
        except Exception as e:
            logger.warning(f"Requests session establishment failed: {e}")
        
        return False
    
    def download_report_with_enhanced_retry(self, report_data, max_retries=5):
        """Download report with multiple fallback strategies"""
        url = report_data['link']
        name = report_data['name']
        
        for attempt in range(max_retries):
            try:
                logger.info(f"Attempt {attempt + 1} for {name}")
                
                # Strategy 1: Selenium with full JS
                if attempt < 3:
                    self.driver.get(url)
                    time.sleep(3)
                    
                    # Check for redirect
                    if "eFD: Home" in self.driver.title:
                        logger.info("Redirected to home, re-establishing session...")
                        self.establish_session()
                        self.driver.get(url)
                        time.sleep(3)
                        
                        if "eFD: Home" in self.driver.title:
                            continue
                    
                    # Save HTML
                    html_content = self.driver.page_source
                    return html_content
                
                # Strategy 2: Direct requests (for non-JS pages)
                else:
                    response = self.session.get(url)
                    if response.status_code == 200:
                        return response.text
                    else:
                        logger.warning(f"Requests failed with status {response.status_code}")
                
            except Exception as e:
                logger.error(f"Error on attempt {attempt + 1}: {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)  # Exponential backoff
        
        return None
    
    def extract_transactions_with_fallback(self, html_content):
        """Extract transactions with multiple parsing strategies"""
        transactions = []
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Strategy 1: Standard table parsing
        transactions = self.parse_tables(soup)
        
        # Strategy 2: If no transactions found, try alternative parsing
        if not transactions:
            logger.info("Standard parsing failed, trying alternative methods...")
            transactions = self.parse_alternative(soup)
        
        # Strategy 3: If still no transactions, try regex-based extraction
        if not transactions:
            logger.info("Alternative parsing failed, trying regex extraction...")
            transactions = self.parse_with_regex(html_content)
        
        return transactions
    
    def parse_tables(self, soup):
        """Standard table parsing with enhanced header detection"""
        transactions = []
        tables = soup.find_all('table')
        
        for table in tables:
            rows = table.find_all('tr')
            if len(rows) < 2:
                continue
                
            # Enhanced header detection
            header_cells = rows[0].find_all(['th', 'td'])
            headers = [th.get_text(strip=True).lower() for th in header_cells]
            
            # Flexible header mapping
            header_map = self.create_header_map(headers)
            
            if not header_map:
                continue
                
            # Extract data rows
            for row in rows[1:]:
                cells = row.find_all(['td', 'th'])
                if len(cells) >= 3:
                    transaction = self.extract_transaction_from_cells(cells, header_map)
                    if transaction:
                        transactions.append(transaction)
        
        return transactions
    
    def create_header_map(self, headers):
        """Create flexible header mapping"""
        header_map = {}
        
        # Define possible header names for each field
        field_mappings = {
            'asset': ['asset', 'security', 'name', 'description'],
            'transaction_type': ['transaction', 'type', 'action'],
            'date': ['date', 'transaction date'],
            'amount': ['amount', 'value'],
            'owner': ['owner'],
            'ticker': ['ticker', 'symbol']
        }
        
        for field, possible_names in field_mappings.items():
            for idx, header in enumerate(headers):
                if any(name in header for name in possible_names):
                    header_map[field] = idx
                    break
        
        return header_map
    
    def extract_transaction_from_cells(self, cells, header_map):
        """Extract transaction from cells using header map"""
        cell_texts = [cell.get_text(strip=True) for cell in cells]
        
        transaction = {
            'raw_text': ' | '.join(cell_texts),
            'cell_count': len(cells)
        }
        
        # Extract fields based on header map
        if 'asset' in header_map:
            asset = cell_texts[header_map['asset']]
            transaction['asset'] = asset
            transaction['ticker'] = self.extract_ticker(asset)
        
        if 'transaction_type' in header_map:
            transaction['transaction_type'] = cell_texts[header_map['transaction_type']]
        
        if 'date' in header_map:
            transaction['date'] = cell_texts[header_map['date']]
        
        if 'amount' in header_map:
            transaction['amount'] = cell_texts[header_map['amount']]
        
        if 'owner' in header_map:
            owner = cell_texts[header_map['owner']]
            transaction['owner'] = owner
            transaction['relationship'] = self.identify_transaction_owner(owner)
        
        return transaction
    
    def parse_alternative(self, soup):
        """Alternative parsing for non-standard table formats"""
        transactions = []
        
        # Look for div-based transaction layouts
        transaction_divs = soup.find_all('div', class_=re.compile(r'transaction|asset', re.I))
        
        for div in transaction_divs:
            text = div.get_text(strip=True)
            if self.is_likely_transaction(text):
                transaction = self.parse_transaction_text(text)
                if transaction:
                    transactions.append(transaction)
        
        return transactions
    
    def parse_with_regex(self, html_content):
        """Regex-based extraction as last resort"""
        transactions = []
        
        # Pattern to match transaction-like text blocks
        transaction_pattern = r'([A-Za-z\s]+)\s*(Purchase|Sale|Exchange)\s*(\d{1,2}/\d{1,2}/\d{4})\s*(\$[\d,]+-\$[\d,]+|\$[\d,]+)'
        matches = re.findall(transaction_pattern, html_content, re.IGNORECASE)
        
        for match in matches:
            asset, transaction_type, date, amount = match
            transaction = {
                'asset': asset.strip(),
                'transaction_type': transaction_type,
                'date': date,
                'amount': amount,
                'ticker': self.extract_ticker(asset),
                'owner': 'self',  # Default
                'relationship': 'self'
            }
            transactions.append(transaction)
        
        return transactions
    
    def is_likely_transaction(self, text):
        """Check if text likely contains transaction data"""
        keywords = ['purchase', 'sale', 'exchange', 'asset', 'security', '$', 'ticker']
        return any(keyword.lower() in text.lower() for keyword in keywords)
    
    def parse_transaction_text(self, text):
        """Parse transaction from free text"""
        # Extract components using regex
        asset_match = re.search(r'([A-Za-z\s]+(?:Inc|Corp|LLC|Ltd|ETF)?)', text)
        type_match = re.search(r'(Purchase|Sale|Exchange)', text, re.IGNORECASE)
        date_match = re.search(r'(\d{1,2}/\d{1,2}/\d{4})', text)
        amount_match = re.search(r'(\$[\d,]+-\$[\d,]+|\$[\d,]+)', text)
        
        if asset_match and type_match and date_match and amount_match:
            return {
                'asset': asset_match.group(1).strip(),
                'transaction_type': type_match.group(1),
                'date': date_match.group(1),
                'amount': amount_match.group(1),
                'ticker': self.extract_ticker(asset_match.group(1)),
                'owner': 'self',
                'relationship': 'self'
            }
        
        return None
    
    def extract_ticker(self, asset_text):
        """Extract ticker symbol with enhanced patterns"""
        # Standard pattern: (AAPL) or [AAPL]
        match = re.search(r'[(\[]([A-Z]{1,5})[)\]]', asset_text)
        if match:
            return match.group(1)
        
        # Alternative pattern: AAPL - 
        match = re.search(r'([A-Z]{1,5})\s*-', asset_text)
        if match:
            return match.group(1)
        
        # Another pattern: - AAPL
        match = re.search(r'-\s*([A-Z]{1,5})', asset_text)
        if match:
            return match.group(1)
        
        return None
    
    def identify_transaction_owner(self, asset_text):
        """Identify transaction owner with enhanced patterns"""
        asset_text = asset_text.lower()
        
        # Spouse indicators
        if any(indicator in asset_text for indicator in ['spouse', 'husband', 'wife', 'joint', 'spousal']):
            return 'spouse'
        
        # Child indicators
        if any(indicator in asset_text for indicator in ['child', 'son', 'daughter', 'dependent', 'minor']):
            return 'child'
        
        # Other family
        if any(indicator in asset_text for indicator in ['family', 'trust', 'estate']):
            return 'family'
        
        return 'self'
    
    def process_report(self, report_data):
        """Process a single report with enhanced error handling"""
        logger.info(f"Processing report: {report_data['name']}")
        
        # Download HTML
        html_content = self.download_report_with_enhanced_retry(report_data)
        
        if not html_content:
            logger.error(f"Failed to download report: {report_data['name']}")
            return None
        
        # Extract transactions
        transactions = self.extract_transactions_with_fallback(html_content)
        
        # Create report data
        report_result = {
            'name': report_data['name'],
            'link': report_data['link'],
            'date_filed': report_data.get('date_filed'),
            'office': report_data.get('office'),
            'report_type': report_data.get('report_type'),
            'transactions': transactions,
            'transaction_count': len(transactions),
            'extraction_date': datetime.now().isoformat(),
            'extraction_success': len(transactions) > 0 or 'No transactions' in html_content
        }
        
        # Save raw HTML for debugging
        html_file = f"C:\\EMPIRE\\SATORI_Scraper\\data\\raw\\senate\\{report_data['name'].replace(' ', '_')}.html"
        with open(html_file, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        return report_result
    
    def close(self):
        """Clean up resources"""
        if self.driver:
            self.driver.quit()
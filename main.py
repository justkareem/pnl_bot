import os
import json
import logging
import telebot
from PIL import Image, ImageDraw, ImageFont
import requests
import time
from datetime import datetime
from typing import Dict, List, Optional

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot configuration
TOKEN = "8000534296:AAEIc6Fqm1eMD8H3dpl0OsN-wofhdgEnDvs"
bot = telebot.TeleBot(TOKEN)

# File to store user wallet addresses
USERS_FILE = "user_wallets.json"

# Ensure the users file exists
if not os.path.exists(USERS_FILE):
    with open(USERS_FILE, "w") as f:
        json.dump({}, f)


def save_wallet(user_id: int, wallet_address: str) -> bool:
    """Save a user's wallet address to the JSON file."""
    try:
        with open(USERS_FILE, "r") as f:
            users = json.load(f)

        users[str(user_id)] = wallet_address

        with open(USERS_FILE, "w") as f:
            json.dump(users, f, indent=4)

        return True
    except Exception as e:
        logger.error(f"Error saving wallet: {str(e)}")
        return False


def get_wallet(user_id: int) -> Optional[str]:
    """Get a user's wallet address from the JSON file."""
    try:
        with open(USERS_FILE, "r") as f:
            users = json.load(f)

        return users.get(str(user_id))
    except Exception as e:
        logger.error(f"Error getting wallet: {str(e)}")
        return None


class SolanaPnLCalculator:
    """
    A class to calculate PnL for a specific token in a Solana wallet.
    """

    def __init__(self, wallet_address: str, token_mint: str):
        """
        Initialize the calculator with wallet address and token mint.

        Args:
            wallet_address: Solana wallet address
            token_mint: Token mint address
        """
        self.wallet_address = wallet_address
        self.token_mint = token_mint
        self.base_url = "https://api-v2.solscan.io/v2"
        self.headers = {
            "accept": "application/json, text/plain, */*",
            "accept-language": "en-US,en;q=0.9,ro;q=0.8",
            "if-none-match": 'W/"11414-9NGmPeD4XF+B6LmSOOAkLfPFsAo"',
            "origin": "https://solscan.io",
            "priority": "u=1, i",
            "sec-ch-ua": '"Chromium";v="134", "Not:A-Brand";v="24", "Microsoft Edge";v="134"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-site",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36 Edg/134.0.0.0"
        }
        self.token_accounts = []
        self.transfers = []
        self.transactions = []
        self.token_info = None
        self.sol_price = None

    def get_token_accounts(self) -> List[Dict]:
        """
        Get all token accounts for the wallet that hold the specified token.

        Returns:
            List of token accounts
        """
        url = f"{self.base_url}/account/tokenaccounts"
        params = {
            "address": self.wallet_address,
            "page": 1,
            "page_size": 480,
            "type": "token",
            "hide_zero": False,
            "filter": self.token_mint
        }

        response = requests.get(url, headers=self.headers, params=params)
        if response.status_code != 200:
            raise Exception(f"Failed to get token accounts: {response.status_code}")

        data = response.json()
        if not data.get("success"):
            raise Exception("API request was not successful")

        token_accounts = []
        for account in data.get("data", {}).get("tokenAccounts", []):
            if account.get("tokenAddress") == self.token_mint:
                token_accounts.append(account)

        self.token_accounts = token_accounts
        return token_accounts

    def get_transfers_for_token_account(self, token_account: str, page_size: int = 100) -> List[Dict]:
        """
        Get all transfers for a specific token account.

        Args:
            token_account: Token account address
            page_size: Number of transfers to fetch per page

        Returns:
            List of transfers
        """
        url = f"{self.base_url}/account/transfer"
        params = {
            "address": self.wallet_address,
            "page": 1,
            "page_size": 100,
            "remove_spam": "true",
            "exclude_amount_zero": "true",
            "token_account": token_account
        }

        response = requests.get(url, headers=self.headers, params=params)
        if response.status_code != 200:
            raise Exception(f"Failed to get transfers: {response.status_code}")

        data = response.json()
        if not data.get("success"):
            raise Exception("API request was not successful")

        transfers = data.get("data", [])

        # Get token info from metadata
        if "metadata" in data and "tokens" in data["metadata"] and self.token_mint in data["metadata"]["tokens"]:
            self.token_info = data["metadata"]["tokens"][self.token_mint]

        # Get SOL price
        if "metadata" in data and "tokens" in data["metadata"] and "So11111111111111111111111111111111111111111" in \
                data["metadata"]["tokens"]:
            self.sol_price = data["metadata"]["tokens"]["So11111111111111111111111111111111111111111"].get("price_usdt",
                                                                                                           0)

        return transfers

    def get_transactions(self, token_account: str = None, page_size: int = 100) -> List[Dict]:
        """
        Get all transactions for the wallet or a specific token account.

        Args:
            token_account: Token account address (optional)
            page_size: Number of transactions to fetch per page

        Returns:
            List of transactions
        """
        url = f"{self.base_url}/account/transaction"
        params = {
            "address": token_account if token_account else self.wallet_address,
            "page_size": 40
        }

        response = requests.get(url, headers=self.headers, params=params)
        if response.status_code != 200:
            raise Exception(f"Failed to get transactions: {response.status_code}")

        data = response.json()
        if not data.get("success"):
            raise Exception("API request was not successful")

        transactions = data.get("data", {}).get("transactions", [])

        # Get SOL price if not already set
        if not self.sol_price and "metadata" in data and "tokens" in data[
            "metadata"] and "So11111111111111111111111111111111111111111" in data["metadata"]["tokens"]:
            self.sol_price = data["metadata"]["tokens"]["So11111111111111111111111111111111111111111"].get("price_usdt",
                                                                                                           0)

        return transactions

    def get_all_transfers_and_transactions(self):
        """
        Get all transfers and transactions for the token.
        """
        if not self.token_accounts:
            self.get_token_accounts()

        all_transfers = []
        all_transactions = []

        for account in self.token_accounts:
            token_account = account["address"]

            # Get transfers for this token account
            transfers = self.get_transfers_for_token_account(token_account)
            all_transfers.extend(transfers)

            # Get transactions for this token account
            transactions = self.get_transactions(token_account)
            all_transactions.extend(transactions)

            time.sleep(1)  # Be nice to the API

        self.transfers = all_transfers

        # For transactions, we should also get the wallet's transactions
        # as they may contain token purchase/sale transactions
        wallet_transactions = self.get_transactions()

        # Filter transactions that are related to the token
        relevant_transactions = []
        for tx in wallet_transactions:
            # Check if transaction contains relevant instructions
            instructions = tx.get("parsedInstruction", [])
            relevant = False
            for instr in instructions:
                # Look for 'buy' or 'sell' instructions with 'pump' program
                if (instr.get("type") in ["buy", "sell"] and
                        instr.get("program") == "pump"):
                    relevant = True
                    break

                # Look for token transfers related to our token
                if (instr.get("type") == "transfer" and
                        instr.get("program") == "spl-token"):
                    relevant = True
                    break

            if relevant:
                # Add token identifier for filtering later
                tx["relevant_for_token"] = True
                relevant_transactions.append(tx)

        all_transactions.extend(relevant_transactions)

        # Remove duplicates by txHash
        unique_transactions = {tx.get("txHash", ""): tx for tx in all_transactions if "txHash" in tx}
        self.transactions = list(unique_transactions.values())

        return self.transfers, self.transactions

    def match_transfers_with_transactions(self):
        """
        Match transfers with corresponding transactions to get accurate cost data.

        Returns:
            List of enriched transfer records
        """
        if not self.transfers or not self.transactions:
            self.get_all_transfers_and_transactions()

        # Create a dictionary of transactions by txHash for quick lookup
        tx_dict = {tx.get("txHash", ""): tx for tx in self.transactions if "txHash" in tx}

        enriched_transfers = []

        for transfer in self.transfers:
            trans_id = transfer.get("trans_id", "")
            if trans_id in tx_dict:
                transaction = tx_dict[trans_id]
                # Extract sol_value and calculate cost in USD
                sol_value = float(transaction.get("sol_value", 0)) / 1e9  # Convert lamports to SOL
                sol_price = self.sol_price or 0
                cost_usd = sol_value * sol_price

                # Create an enriched record
                enriched_transfer = transfer.copy()
                enriched_transfer["sol_value"] = sol_value
                enriched_transfer["sol_price"] = sol_price
                enriched_transfer["cost_usd"] = cost_usd

                enriched_transfers.append(enriched_transfer)
            else:
                # If no matching transaction found, just add the transfer as is
                enriched_transfers.append(transfer)

        return enriched_transfers

    def calculate_pnl(self) -> Dict:
        """
        Calculate PnL for the token using matched transfer and transaction data.

        Returns:
            Dictionary with PnL information
        """
        enriched_transfers = self.match_transfers_with_transactions()

        if not enriched_transfers:
            return {
                "token_symbol": None,
                "token_name": None,
                "total_bought": 0,
                "total_cost_usd": 0,
                "total_cost_sol": 0,
                "total_sold": 0,
                "total_revenue": 0,
                "current_balance": 0,
                "current_value": 0,
                "realized_pnl": 0,
                "unrealized_pnl": 0,
                "total_pnl": 0,
                "roi_percentage": 0,
                "transfers": []
            }

        # Sort transfers by block_time
        sorted_transfers = sorted(enriched_transfers, key=lambda x: x["block_time"])

        # Calculate buys, sells, and current balance
        total_bought = 0
        total_cost_usd = 0
        total_cost_sol = 0
        total_sold = 0
        total_revenue = 0
        current_balance = 0
        total_sold_sol = 0

        transfer_details = []

        decimals = self.token_info.get("token_decimals", 0) if self.token_info else 0
        token_symbol = self.token_info.get("token_symbol", "") if self.token_info else ""
        token_name = self.token_info.get("token_name", "") if self.token_info else ""

        for transfer in sorted_transfers:
            amount = transfer.get("amount", 0)
            value = transfer.get("value", 0)  # Value of tokens in USD
            flow = transfer.get("flow", "")

            # Convert amount based on decimals
            amount_decimal = amount / (10 ** decimals)

            # Get cost from matched transaction if available
            sol_value = transfer.get("sol_value", 0)
            cost_usd = transfer.get("cost_usd", 0)

            timestamp = datetime.fromtimestamp(transfer.get("block_time", 0))

            transfer_info = {
                "timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                "transaction_id": transfer.get("trans_id", ""),
                "flow": flow,
                "amount": amount_decimal,
                "token_value_usd": value,
                "sol_value": sol_value,
                "cost_usd": cost_usd,
                "price_per_token": value / amount_decimal if amount_decimal else 0
            }

            if flow == "in":
                total_bought += amount_decimal
                total_cost_usd += cost_usd if cost_usd > 0 else value  # Fallback to token value if cost not available
                total_cost_sol += sol_value
                current_balance += amount_decimal
            elif flow == "out":
                total_sold_sol += sol_value
                total_sold += amount_decimal
                total_revenue += value
                current_balance -= amount_decimal

            transfer_details.append(transfer_info)

        # Calculate current value using the latest price
        if current_balance < 0:
            total_bought = total_bought + current_balance * -1 * self.sol_price
            current_balance = 0
        current_price = self.token_info.get("price_usdt", 0) if self.token_info else 0
        current_value = current_balance * current_price

        # Calculate PnL
        avg_cost_per_token = total_cost_usd / total_bought if total_bought else 0
        realized_pnl = total_sold_sol - total_cost_sol
        unrealized_pnl = current_value / self.sol_price
        total_pnl = realized_pnl + unrealized_pnl

        # Calculate ROI
        roi_percentage = (total_pnl / total_cost_sol * 100) if total_cost_sol else 0
        return {
            "token_symbol": token_symbol,
            "token_name": token_name,
            "total_bought": total_bought,
            "total_cost_usd": total_cost_usd,
            "total_cost_sol": total_cost_sol,
            "total_sold": total_sold,
            "total_revenue": total_revenue,
            "current_balance": current_balance,
            "current_value": current_value,
            "realized_pnl": realized_pnl,
            "unrealized_pnl": unrealized_pnl,
            "total_pnl": total_pnl,
            "roi_percentage": roi_percentage,
            "transfers": transfer_details
        }


def create_gradient_text(text, font, position, gradient_colors, text_size):
    """Creates text filled with a linear gradient."""
    width, height = text_size
    # Create an empty RGB image
    gradient = Image.new("RGB", (width, height), color=0)
    # Create the gradient effect (from color 1 to color 2)
    for y in range(height):
        blend = y / height  # Blend factor from 0 to 1
        r = int((1 - blend) * int(gradient_colors[0][1:3], 16) + blend * int(gradient_colors[1][1:3], 16))
        g = int((1 - blend) * int(gradient_colors[0][3:5], 16) + blend * int(gradient_colors[1][3:5], 16))
        b = int((1 - blend) * int(gradient_colors[0][5:7], 16) + blend * int(gradient_colors[1][5:7], 16))
        ImageDraw.Draw(gradient).line([(0, y), (width, y)], fill=(r, g, b))

    # Create a transparent text mask
    text_mask = Image.new("L", (width, height), 0)  # 'L' mode (grayscale)
    draw_mask = ImageDraw.Draw(text_mask)
    draw_mask.text(position, text, font=font, fill=255)  # White text on black background

    # Apply text mask to gradient
    gradient_text = Image.new("RGBA", (width, height), (0, 0, 0, 0))  # Transparent
    gradient_text.paste(gradient, (0, 0), text_mask)

    return gradient_text


def generate_investment_card(template_path, output_path, token_name="", percentage="", bought_amount="",
                             holding_amount="", profit_sol="", profit_usd=""):
    """Generate investment card with the given parameters."""
    # Open template and convert to RGBA
    template = Image.open(template_path).convert("RGBA")
    draw = ImageDraw.Draw(template)
    try:
        percentage = f"{'+' if float(percentage) >= 0 else ''}{percentage}"
        profit_sol = f"{'+' if float(profit_sol) >= 0 else ''}{profit_sol}"
        profit_usd = f"{'+$' if float(profit_usd) >= 0 else '-$'}{profit_usd[1:]}"
    except Exception as e:
        logger.error(e)
    # Load fonts
    try:
        title_font = ImageFont.truetype("fonts/YapariTrial-Bold.ttf", 100)
        percentage_font = ImageFont.truetype("fonts/Exo2-Bold.ttf", 120)
        label_font = ImageFont.truetype("fonts/Exo2-VariableFont_wght.ttf", 50)
        label_font_2 = ImageFont.truetype("fonts/Exo2-Bold.ttf", 60)
        tag_font = ImageFont.truetype("fonts/Exo2-Bold.ttf", 60)
    except IOError:
        print("Font not found, using default font.")
        title_font = ImageFont.load_default()
        percentage_font = ImageFont.load_default()
        label_font = ImageFont.load_default()
        label_font_2 = ImageFont.load_default()
        tag_font = ImageFont.load_default()

    # Draw token name
    draw.text((200, 300), token_name, fill=(255, 255, 255), font=title_font)

    # Generate gradient text for percentage
    percentage_position = (200, 400)
    text_size = (600, 150)  # Define the size of the area for gradient text
    gradient_text = create_gradient_text(
        f"{percentage}%", percentage_font, (0, 0), ["#ff3131", "#ffffff"], text_size
    )

    # Paste the gradient text onto the template
    template.paste(gradient_text, percentage_position, gradient_text)

    # Add data values
    if bought_amount:
        draw.text((600, 610), f"{bought_amount} SOL", fill=(255, 255, 255), font=label_font_2)

    if holding_amount:
        draw.text((200, 1000), f"{holding_amount}", fill=(255, 255, 255), font=tag_font)

    if profit_sol:
        draw.text((600, 705), f"{profit_sol} SOL", fill=(255, 255, 255), font=label_font)

    if profit_usd:
        draw.text((600, 850), f"{profit_usd}", fill=(255, 255, 255), font=label_font)

    # Save final image
    template.save(output_path)
    return output_path


def format_number(number):
    """Format numbers for display on the card."""
    if number is None:
        return ""

    abs_num = abs(number)

    if abs_num >= 1_000_000:
        return f"{number / 1_000_000:.1f}M"
    elif abs_num >= 1_000:
        return f"{number / 1_000:.1f}K"
    elif abs_num >= 1:
        return f"{number:.2f}"
    else:
        return f"{number:.4f}"


# Bot command handlers
@bot.message_handler(commands=['start'])
def send_welcome(message):
    """Send welcome message when /start command is issued."""
    bot.reply_to(message, "Welcome to the Solana PnL Card Bot! \n\n" +
                 "Set your wallet address with: /wallet_address <your_wallet_address>\n" +
                 "Then check token PnL with: /mypnl <token_mint_address>")


@bot.message_handler(commands=['wallet_address'])
def set_wallet_address(message):
    """Set user's wallet address."""
    try:
        # Extract wallet address from command
        command_parts = message.text.split(' ', 1)
        if len(command_parts) < 2:
            bot.reply_to(message, "Please provide a wallet address.\nUsage: /wallet_address <your_wallet_address>")
            return

        wallet_address = command_parts[1].strip()

        # Basic validation
        if len(wallet_address) < 32 or len(wallet_address) > 44:
            bot.reply_to(message, "Invalid wallet address. Please provide a valid Solana address.")
            return

        # Save wallet address
        user_id = message.from_user.id
        if save_wallet(user_id, wallet_address):
            bot.reply_to(message, f"Your wallet address has been set to: {wallet_address}")
        else:
            bot.reply_to(message, "Failed to save your wallet address. Please try again later.")

    except Exception as e:
        logger.error(f"Error in set_wallet_address: {str(e)}")
        bot.reply_to(message, "An error occurred. Please try again later.")


@bot.message_handler(commands=['mypnl'])
def generate_pnl_card(message):
    """Generate PnL card for a token."""
    try:
        # Extract token mint address
        command_parts = message.text.split(' ', 1)
        if len(command_parts) < 2:
            bot.reply_to(message, "Please provide a token mint address.\nUsage: /mypnl <token_mint_address>")
            return

        token_mint = command_parts[1].strip()

        # Get user's wallet address
        user_id = message.from_user.id
        wallet_address = get_wallet(user_id)

        if not wallet_address:
            bot.reply_to(message,
                         "You haven't set your wallet address yet.\nUse /wallet_address <your_wallet_address> to set it.")
            return

        # Send "processing" message
        processing_msg = bot.reply_to(message, "Processing your request, please wait...")

        # Calculate PnL
        calculator = SolanaPnLCalculator(wallet_address, token_mint)
        pnl_data = calculator.calculate_pnl()

        # Check if token exists in wallet
        if not pnl_data["token_symbol"] and not pnl_data["token_name"]:
            bot.edit_message_text("Token not found in your wallet. Please check the token mint address.",
                                  message.chat.id, processing_msg.message_id)
            return

        # Generate card image
        output_path = f"pnl_card_{user_id}_{int(time.time())}.png"
        template_path = "template/template_full.png"  # Make sure this exists

        # Format data for card
        token_name = f"${pnl_data['token_symbol']}" if pnl_data['token_symbol'] else pnl_data['token_name']
        percentage = str(int(pnl_data['roi_percentage'])) if abs(
            pnl_data['roi_percentage']) > 100 else f"{pnl_data['roi_percentage']:.1f}"
        bought_amount = format_number(pnl_data['total_cost_sol'])
        profit_sol = format_number(pnl_data['total_pnl'])
        if pnl_data['total_pnl'] * calculator.sol_price > 0:
            profit_usd = '+$' + format_number(pnl_data['total_pnl'] * calculator.sol_price)
        else:
            '-$' + format_number(pnl_data['total_pnl'] * calculator.sol_price * -1)

        # Get username
        username = f"@{message.from_user.username}" if message.from_user.username else f"user{user_id}"

        # Generate card
        generate_investment_card(
            template_path=template_path,
            output_path=output_path,
            token_name=token_name,
            percentage=percentage,
            bought_amount=bought_amount,
            holding_amount=username,
            profit_sol=profit_sol,
            profit_usd=profit_usd
        )

        # Send card to user
        with open(output_path, 'rb') as photo:
            bot.send_photo(message.chat.id, photo)

        # Delete processing message
        bot.delete_message(message.chat.id, processing_msg.message_id)

        # Delete the generated image
        if os.path.exists(output_path):
            os.remove(output_path)

    except Exception as e:
        logger.error(f"Error in generate_pnl_card: {str(e)}")
        bot.reply_to(message, f"An error occurred")


def main():
    """Start the bot."""
    logger.info("Starting bot...")
    bot.polling(none_stop=True)


if __name__ == "__main__":
    main()

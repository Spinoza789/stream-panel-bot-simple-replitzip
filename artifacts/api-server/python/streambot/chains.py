"""Read-only mainnet payment checks using an explicitly trusted HTTP provider.

No signing, broadcasting, price conversion, or floating-point money arithmetic.
The caller must compare ``amount_units`` with the invoice and atomically prevent
transaction reuse. A dishonest RPC provider is outside this verifier's trust
boundary; use a node you control or a reputable authenticated provider.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

import requests


class PaymentPending(Exception):
    """Transaction not yet visible, canonical, or sufficiently final.

    ``confirmations``/``required`` carry the live progress when the chain supplied it so
    the customer can be shown "3 of 12 confirmations"; ``stage`` is ``'finality'`` once the
    confirmation count is met and only the network's finality checkpoint is outstanding.
    """

    def __init__(self, message='', *, confirmations=None, required=None, stage=None):
        super().__init__(message)
        self.confirmations = confirmations
        self.required = required
        self.stage = stage


class PaymentRejected(Exception):
    """Transaction cannot pay the requested invoice."""


class ChainUnavailable(Exception):
    """Provider unavailable or unable to supply trustworthy data."""


# Issuer-published addresses, not token names or caller-supplied lookalikes:
# https://developers.circle.com/stablecoins/usdc-contract-addresses
# https://tether.to/en/supported-protocols/
ETHEREUM_TOKENS = {
    'USDT': '0xdac17f958d2ee523a2206206994597c13d831ec7',
    'USDC': '0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48',
}
SOLANA_TOKENS = {
    'USDT': 'Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB',
    'USDC': 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',
}
# https://github.com/solana-labs/solana/blob/master/sdk/src/genesis_config.rs
SOLANA_GENESIS = '5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d'
# https://github.com/bitcoin/bitcoin/blob/master/src/kernel/chainparams.cpp
BITCOIN_GENESIS = '000000000019d6689c085ae165831e934ff763ae46a2a6c172b3f1b60a8ce26f'
TRANSFER_TOPIC = '0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef'
TOKEN_PROGRAM = 'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA'
BASE58 = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
TIMEOUT = (5, 20)  # connect, read seconds; every request is bounded.


def _integer(value: Any, name: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ChainUnavailable('Invalid integer in provider field: ' + name)
    return value


def _hex(value: Any, size: int, name: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r'0x[0-9a-fA-F]{%d}' % (size * 2), value):
        raise ChainUnavailable('Invalid hex in provider field: ' + name)
    return value.lower()


def _quantity(value: Any, name: str) -> int:
    # JSON-RPC QUANTITY encoding: no missing digits, signs, or leading zeroes.
    if not isinstance(value, str) or not re.fullmatch(r'0x(?:0|[1-9a-fA-F][0-9a-fA-F]*)', value):
        raise ChainUnavailable('Invalid quantity in provider field: ' + name)
    if len(value) > 66:
        raise ChainUnavailable('Ethereum quantity exceeds uint256: ' + name)
    return int(value, 16)


def _base58(value: Any, length: int) -> bool:
    if not isinstance(value, str) or not value or len(value) > length * 2:
        return False
    number = 0
    for char in value:
        if char not in BASE58:
            return False
        number = number * 58 + BASE58.index(char)
    leading_zeroes = len(value) - len(value.lstrip('1'))
    return leading_zeroes + (number.bit_length() + 7) // 8 == length


def _btc_hash(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-fA-F]{64}', value):
        raise ChainUnavailable('Invalid Bitcoin hash from provider')
    return value.lower()


class BlockchainVerifier:
    """``http`` is an injectable requests-compatible Session (get/post)."""

    def __init__(self, http=None):
        self.http = http if http is not None else requests.Session()
        self._request_id = 0

    def verify(self, asset: dict, txid: str, created_at: int, expires_at: int) -> dict:
        self._validate_config(asset)
        network = asset['network']
        try:
            if network == 'ethereum':
                txid = _hex(txid, 32, 'transaction id')
            elif network == 'bitcoin':
                txid = _btc_hash(txid)
            elif not _base58(txid, 64):
                raise ChainUnavailable('Invalid Solana signature')
        except ChainUnavailable as exc:
            raise PaymentRejected('Invalid transaction identifier') from exc
        if type(created_at) is not int or type(expires_at) is not int or not 0 <= created_at <= expires_at:
            raise PaymentRejected('Invalid invoice time window')
        try:
            amount, timestamp, confirmations = getattr(self, '_' + network)(asset, txid)
        except (KeyError, TypeError, IndexError, ValueError, AttributeError, OverflowError) as exc:
            # Missing or malformed provider data must fail closed, never fall back.
            raise ChainUnavailable('Incomplete or malformed chain response') from exc
        if not created_at <= timestamp <= expires_at:
            raise PaymentRejected('Transaction is outside the invoice time window')
        if amount <= 0:
            raise PaymentRejected('No positive payment to the configured recipient')
        return dict(network=network, txid=txid, amount_units=amount,
                    block_time=timestamp, confirmations=confirmations)

    @staticmethod
    def _validate_config(asset: dict) -> None:
        if not isinstance(asset, dict):
            raise PaymentRejected('Invalid asset configuration')
        network, symbol = asset.get('network'), asset.get('symbol')
        token = asset.get('token')
        decimals = asset.get('decimals')
        wallet = asset.get('wallet')
        expected_decimals = None
        if network == 'ethereum':
            if symbol == 'ETH' and token is None:
                expected_decimals = 18
            elif symbol in ETHEREUM_TOKENS and isinstance(token, str) and token.lower() == ETHEREUM_TOKENS[symbol]:
                expected_decimals = 6
            if not isinstance(wallet, str) or not re.fullmatch(r'0x[0-9a-fA-F]{40}', wallet):
                raise PaymentRejected('Invalid Ethereum recipient')
            if type(asset.get('require_finalized', True)) is not bool:
                raise PaymentRejected('Invalid Ethereum finality setting')
        elif network == 'solana':
            if symbol in SOLANA_TOKENS and token == SOLANA_TOKENS[symbol]:
                expected_decimals = 6
            if not _base58(wallet, 32):
                raise PaymentRejected('Invalid Solana recipient owner')
        elif network == 'bitcoin':
            if symbol == 'BTC' and token is None:
                expected_decimals = 8
            if not isinstance(wallet, str) or not wallet or wallet.strip() != wallet:
                raise PaymentRejected('Invalid Bitcoin recipient')
        if expected_decimals is None or type(decimals) is not int or decimals != expected_decimals:
            raise PaymentRejected('Unsupported asset, unofficial token, or incorrect decimals')
        confirmations = asset.get('confirmations', 3 if network == 'bitcoin' else 12 if network == 'ethereum' else 1)
        if type(confirmations) is not int or confirmations < 1:
            raise PaymentRejected('Confirmation count must be a positive integer')
        endpoint = asset.get('rpc_url')
        if not isinstance(endpoint, str):
            raise PaymentRejected('Missing provider endpoint')
        try:
            parsed = urlsplit(endpoint)
        except ValueError as exc:
            raise PaymentRejected('Invalid provider endpoint') from exc
        if parsed.scheme not in ('http', 'https') or not parsed.netloc or parsed.fragment:
            raise PaymentRejected('Invalid provider endpoint')

    def _rpc(self, endpoint: str, method: str, params: list) -> Any:
        self._request_id += 1
        request_id = self._request_id
        try:
            response = self.http.post(endpoint, json={'jsonrpc': '2.0', 'id': request_id,
                                      'method': method, 'params': params}, timeout=TIMEOUT)
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError, TypeError) as exc:
            raise ChainUnavailable('Chain RPC request failed') from exc
        if not isinstance(payload, dict) or payload.get('jsonrpc') != '2.0' or type(payload.get('id')) is not int or payload.get('id') != request_id:
            raise ChainUnavailable('Invalid RPC response envelope')
        if 'error' in payload or 'result' not in payload:
            raise ChainUnavailable('Chain RPC could not fulfill the request')
        return payload['result']

    def _get(self, endpoint: str, path: str, *, text: bool = False, notfound: bool = False) -> Any:
        try:
            response = self.http.get(endpoint.rstrip('/') + path, timeout=TIMEOUT)
            if notfound and response.status_code == 404:
                raise PaymentPending('Transaction not found yet')
            response.raise_for_status()
            return response.text.strip() if text else response.json()
        except (requests.RequestException, ValueError, TypeError) as exc:
            raise ChainUnavailable('Bitcoin provider request failed') from exc

    def _ethereum(self, asset: dict, txid: str) -> tuple[int, int, int]:
        endpoint = asset['rpc_url']
        rpc = lambda method, params: self._rpc(endpoint, method, params)
        if _quantity(rpc('eth_chainId', []), 'chainId') != 1:
            raise PaymentRejected('Provider is not Ethereum mainnet')
        receipt = rpc('eth_getTransactionReceipt', [txid])
        if receipt is None:
            raise PaymentPending('Transaction is not mined yet')
        if _hex(receipt['transactionHash'], 32, 'receipt transactionHash') != txid:
            raise PaymentRejected('Receipt transaction hash does not match')
        status = _quantity(receipt['status'], 'receipt status')
        if status == 0:
            raise PaymentRejected('Ethereum transaction reverted')
        if status != 1:
            raise ChainUnavailable('Unrecognized Ethereum receipt status')
        required = asset.get('confirmations', 12)
        if receipt.get('blockNumber') is None or receipt.get('blockHash') is None:
            raise PaymentPending('Transaction is not mined yet', confirmations=0, required=required)
        height = _quantity(receipt['blockNumber'], 'receipt blockNumber')
        block_hash = _hex(receipt['blockHash'], 32, 'receipt blockHash')
        tx = rpc('eth_getTransactionByHash', [txid])
        if tx is None:
            raise PaymentPending('Transaction unavailable after receipt lookup')
        if _hex(tx['hash'], 32, 'transaction hash') != txid:
            raise PaymentRejected('Transaction hash does not match')
        if tx.get('blockNumber') is None or tx.get('blockHash') is None:
            raise PaymentPending('Transaction is not mined yet', confirmations=0, required=required)
        if _quantity(tx['blockNumber'], 'transaction blockNumber') != height or _hex(tx['blockHash'], 32, 'transaction blockHash') != block_hash:
            raise PaymentPending('Transaction and receipt no longer agree')
        block = rpc('eth_getBlockByNumber', [hex(height), False])
        if block is None:
            raise PaymentPending('Transaction block is no longer canonical')
        if _hex(block['hash'], 32, 'block hash') != block_hash or _quantity(block['number'], 'block number') != height:
            raise PaymentPending('Transaction block is no longer canonical')
        transaction_hashes = [_hex(item, 32, 'block transaction') for item in block['transactions']]
        if txid not in transaction_hashes:
            raise PaymentPending('Transaction not in canonical block')
        timestamp = _quantity(block['timestamp'], 'block timestamp')
        head = rpc('eth_getBlockByNumber', ['latest', False])
        if head is None:
            raise ChainUnavailable('Latest block unavailable')
        confirmations = _quantity(head['number'], 'latest block number') - height + 1
        if confirmations < required:
            raise PaymentPending('Ethereum confirmations are insufficient', confirmations=max(confirmations, 0), required=required)
        if asset.get('require_finalized', True):
            finalized = rpc('eth_getBlockByNumber', ['finalized', False])
            if finalized is None:
                raise ChainUnavailable('Finalized head unavailable')
            if _quantity(finalized['number'], 'finalized block number') < height:
                raise PaymentPending('Ethereum transaction is not finalized', confirmations=confirmations, required=required, stage='finality')
        wallet = asset['wallet'].lower()
        if asset['symbol'] == 'ETH':
            if tx.get('to') is None or _hex(tx['to'], 20, 'transaction recipient') != wallet:
                raise PaymentRejected('Native ETH must be transferred directly to the recipient')
            if _hex(tx['from'], 20, 'transaction sender') == wallet:
                raise PaymentRejected('Self-transfers do not pay invoices')
            if tx['input'] != '0x':
                raise PaymentRejected('Native ETH payment must be a plain direct transfer')
            amount = _quantity(tx['value'], 'transaction value')
        else:
            amount = self._erc20_net(receipt, asset['token'].lower(), wallet, txid, block_hash, height)
        return amount, timestamp, confirmations

    @staticmethod
    def _erc20_net(receipt: dict, token: str, wallet: str, txid: str, block_hash: str, height: int) -> int:
        logs = receipt['logs']
        if not isinstance(logs, list):
            raise ChainUnavailable('Missing receipt logs')
        amount = 0
        indices = set()
        for log in logs:
            if _hex(log['address'], 20, 'log address') != token:
                continue
            topics = log['topics']
            if not isinstance(topics, list):
                raise ChainUnavailable('Malformed token topics')
            if not topics or _hex(topics[0], 32, 'event signature') != TRANSFER_TOPIC:
                continue
            if len(topics) != 3:
                raise ChainUnavailable('Malformed token Transfer event')
            if type(log['removed']) is not bool:
                raise ChainUnavailable('Missing log canonicality metadata')
            if log['removed'] or _hex(log['blockHash'], 32, 'log blockHash') != block_hash or _quantity(log['blockNumber'], 'log blockNumber') != height:
                raise PaymentPending('Token log is not canonical')
            if _hex(log['transactionHash'], 32, 'log transactionHash') != txid:
                raise ChainUnavailable('Token log belongs to another transaction')
            index = _quantity(log['logIndex'], 'log index')
            if index in indices:
                raise ChainUnavailable('Duplicate token log')
            indices.add(index)
            source = _hex(topics[1], 32, 'Transfer sender')
            target = _hex(topics[2], 32, 'Transfer recipient')
            if source[2:26] != '0' * 24 or target[2:26] != '0' * 24:
                raise ChainUnavailable('Non-address token event topic')
            value = int(_hex(log['data'], 32, 'Transfer amount'), 16)
            if '0x' + target[-40:] == wallet:
                amount += value
            if '0x' + source[-40:] == wallet:
                amount -= value
        return amount

    def _solana(self, asset: dict, txid: str) -> tuple[int, int, int]:
        endpoint = asset['rpc_url']
        if self._rpc(endpoint, 'getGenesisHash', []) != SOLANA_GENESIS:
            raise PaymentRejected('Provider is not Solana mainnet')
        tx = self._rpc(endpoint, 'getTransaction', [txid, {
            'commitment': 'finalized', 'encoding': 'jsonParsed',
            'maxSupportedTransactionVersion': 0}])
        required = asset.get('confirmations', 1)
        if tx is None:
            raise PaymentPending('Solana transaction not finalized or not found', confirmations=0, required=required)
        signatures = tx['transaction']['signatures']
        if not isinstance(signatures, list) or not signatures or signatures[0] != txid:
            raise PaymentRejected('Solana transaction signature does not match')
        meta = tx['meta']
        if meta['err'] is not None:
            raise PaymentRejected('Solana transaction failed')
        if tx['blockTime'] is None:
            raise ChainUnavailable('Solana block time unavailable')
        timestamp = _integer(tx['blockTime'], 'blockTime')
        slot = _integer(tx['slot'], 'transaction slot')
        head = _integer(self._rpc(endpoint, 'getSlot', [{'commitment': 'finalized'}]), 'finalized slot')
        confirmations = head - slot + 1
        if confirmations < required:
            raise PaymentPending('Solana slot has not reached the required finality', confirmations=max(confirmations, 0), required=required)
        keys = tx['transaction']['message']['accountKeys']
        if not isinstance(keys, list):
            raise ChainUnavailable('Missing Solana transaction accounts')
        pre = self._token_balances(meta['preTokenBalances'], asset, len(keys))
        post = self._token_balances(meta['postTokenBalances'], asset, len(keys))
        amount = sum(post.values()) - sum(pre.values())
        return amount, timestamp, confirmations

    @staticmethod
    def _token_balances(balances: list, asset: dict, account_count: int) -> dict[int, int]:
        if not isinstance(balances, list):
            raise ChainUnavailable('Missing Solana token balances')
        result = {}
        indices = set()
        for balance in balances:
            index = _integer(balance['accountIndex'], 'token account index')
            if index >= account_count or index in indices:
                raise ChainUnavailable('Invalid or duplicate Solana token account index')
            indices.add(index)
            if balance['mint'] != asset['token']:
                continue
            owner = balance['owner']
            if not _base58(owner, 32):
                raise ChainUnavailable('Missing Solana token owner metadata')
            if balance.get('programId', TOKEN_PROGRAM) != TOKEN_PROGRAM:
                raise ChainUnavailable('Official mint reported with unexpected token program')
            units = balance['uiTokenAmount']
            if type(units['decimals']) is not int or units['decimals'] != asset['decimals']:
                raise ChainUnavailable('Solana token decimals disagree with official mint')
            raw = units['amount']
            if not isinstance(raw, str) or not re.fullmatch(r'(?:0|[1-9][0-9]*)', raw):
                raise ChainUnavailable('Malformed Solana token amount')
            amount = int(raw)
            if amount > 2**64 - 1:
                raise ChainUnavailable('Solana token amount exceeds uint64')
            if owner == asset['wallet']:
                result[index] = amount
        return result

    def _bitcoin(self, asset: dict, txid: str) -> tuple[int, int, int]:
        endpoint = asset['rpc_url']
        if _btc_hash(self._get(endpoint, '/block-height/0', text=True)) != BITCOIN_GENESIS:
            raise PaymentRejected('Provider is not Bitcoin mainnet')
        tx = self._get(endpoint, '/tx/' + txid, notfound=True)
        if _btc_hash(tx['txid']) != txid:
            raise PaymentRejected('Bitcoin transaction id does not match')
        status = tx['status']
        if type(status['confirmed']) is not bool:
            raise ChainUnavailable('Invalid Bitcoin confirmation status')
        required = asset.get('confirmations', 3)
        if not status['confirmed']:
            raise PaymentPending('Bitcoin transaction is unconfirmed', confirmations=0, required=required)
        height = _integer(status['block_height'], 'Bitcoin block height')
        block_hash = _btc_hash(status['block_hash'])
        canonical_hash = _btc_hash(self._get(endpoint, '/block-height/' + str(height), text=True))
        if canonical_hash != block_hash:
            raise PaymentPending('Bitcoin transaction block is no longer canonical')
        tip = self._get(endpoint, '/blocks/tip/height', text=True)
        if not re.fullmatch(r'(?:0|[1-9][0-9]*)', tip):
            raise ChainUnavailable('Invalid Bitcoin tip height')
        confirmations = int(tip) - height + 1
        if confirmations < required:
            raise PaymentPending('Bitcoin confirmations are insufficient', confirmations=max(confirmations, 0), required=required)
        timestamp = _integer(status['block_time'], 'Bitcoin block time')
        outputs = tx['vout']
        if not isinstance(outputs, list):
            raise ChainUnavailable('Missing Bitcoin outputs')
        amount = 0
        wallet = asset['wallet']
        if wallet.lower().startswith('bc1'):
            wallet = wallet.lower()
        for output in outputs:
            value = _integer(output['value'], 'Bitcoin output value')
            if value > 21_000_000 * 100_000_000:
                raise ChainUnavailable('Invalid Bitcoin output amount')
            address = output.get('scriptpubkey_address')
            if isinstance(address, str) and address.lower().startswith('bc1'):
                address = address.lower()
            if address == wallet:
                amount += value
        return amount, timestamp, confirmations

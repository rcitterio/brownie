#!/usr/bin/python3

import eth_keys
import json
import os

from lib.components.eth import web3, wei, TransactionReceipt, VirtualMachineError
from lib.components import config
CONFIG = config.CONFIG

class Accounts(list):

    def __init__(self, accounts):
        super().__init__([Account(i) for i in accounts])

    def add(self, priv_key = None):
        if not priv_key:
            priv_key=web3.sha3(os.urandom(8192))
        w3account = web3.eth.account.privateKeyToAccount(priv_key)
        if w3account.address in self:
            return self.at(w3account.address)
        account = LocalAccount(w3account.address, w3account, priv_key)
        self.append(account)
        return account
    
    def at(self, address):
        address = web3.toChecksumAddress(address)
        try:
            return next(i for i in self if i == address)
        except StopIteration:
            print("ERROR: No account exists for {}".format(address))


class _AccountBase(str):

    def __init__(self, addr):
        self.address = addr
        self.nonce = web3.eth.getTransactionCount(self.address)

    def __repr__(self):
        return "<Account object '{}'>".format(self.address)

    def __str__(self):
        return self.__repr__()

    def balance(self):
        return web3.eth.getBalance(self.address)

    def deploy(self, contract, *args, **kwargs):
        return contract.deploy(self, *args, **kwargs)
    
    def estimate_gas(self, to, amount, data=""):
        return web3.eth.estimateGas({
            'from':self.address,
            'to':to,
            'data':data,
            'value':wei(amount)
        })
    
    def _gas_limit(self, to, amount, data=""):
        if CONFIG['active_network']['gas_limit']:
            return CONFIG['active_network']['gas_limit']
        return self.estimate_gas(to, amount, data)

    def _gas_price(self):
        return CONFIG['active_network']['gas_price'] or web3.eth.gasPrice


class Account(_AccountBase):

    def transfer(self, to, amount, gas_limit=None, gas_price=None):
        try:
            txid = web3.eth.sendTransaction({
                'from': self.address,
                'to': to,
                'value': wei(amount),
                'gasPrice': wei(gas_price) or self._gas_price(),
                'gas': wei(gas_limit) or self._gas_limit(to, amount)
                })
            self.nonce += 1
            return TransactionReceipt(txid)
        except ValueError as e:
            raise VirtualMachineError(e)

    def _contract_tx(self, fn, args, tx, name):
        tx['from'] = self.address
        if CONFIG['active_network']['gas_price']:
            tx['gasPrice'] = CONFIG['active_network']['gas_price']
        if CONFIG['active_network']['gas_limit']:
            tx['gas'] = CONFIG['active_network']['gas_limit']
        try: txid = fn(*args).transact(tx)
        except ValueError as e:
            raise VirtualMachineError(e)
        self.nonce += 1
        return TransactionReceipt(txid, name=name)


class LocalAccount(_AccountBase):

    def __new__(cls, address, *args):
        return super().__new__(cls, address)

    def __init__(self, address, account, priv_key):
        self._acct = account
        self.private_key = priv_key.hex()
        self.public_key = eth_keys.keys.PrivateKey(priv_key).public_key
        super().__init__(address)

    def transfer(self, to, amount, gas_limit=None, gas_price=None):
        try:
            signed_tx = self._acct.signTransaction({
                'from': self.address,
                'nonce': self.nonce,
                'gasPrice': wei(gas_price) or self._gas_price(),
                'gas': wei(gas_limit) or self._gas_limit(to, amount),
                'to': to,
                'value': wei(amount),
                'data': ""
                }).rawTransaction
            txid = web3.eth.sendRawTransaction(signed_tx)
            self.nonce += 1
            return TransactionReceipt(txid)
        except ValueError as e:
            raise VirtualMachineError(e)

    def _contract_tx(self, fn, args, tx, name):
        try:
            tx.update({
                'from':self.address,
                'nonce':self.nonce,
                'gasPrice': self._gas_price(),
                'gas': (
                    CONFIG['active_network']['gas_limit'] or
                    fn(*args).estimateGas({'from': self.address})
                )
                })
            raw = fn(*args).buildTransaction(tx)
            txid = web3.eth.sendRawTransaction(
                self._acct.signTransaction(raw).rawTransaction)
            self.nonce += 1
            return TransactionReceipt(txid, name=name)
        except ValueError as e:
            raise VirtualMachineError(e)

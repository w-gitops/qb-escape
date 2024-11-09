#!/usr/bin/python
#
# A simple QuickBooks list importer.
#
# See https://lwn.net/Articles/729087/ for the article that describes
# this program.
#
# Copyright 2017 Jonathan Corbet.
# This program may be distributed under the terms of the GNU General
# Public License, version 2 or later.
#
# This program is provided with no warranty of any kind.  You, and only
# you, are responsible for the integrity of your accounting data.
#
import sys
# If needed, Uncomment the below line and modify with your 
# site-package path containing gnucash bindings.
# See instructions for more info.
# sys.path.insert(0, "/my/path/to/site-packages/gnucash")  
import re, argparse, os
import iif
import remap
import gnucash
from gnucash import gnucash_business, gnucash_core_c


#
# Map QB account types to GC
#
AccountTypeMap = {
    'BANK':	gnucash.ACCT_TYPE_BANK,
    'CCARD':	gnucash.ACCT_TYPE_CREDIT,
    'OCASSET':	gnucash.ACCT_TYPE_ASSET,
    'OASSET':	gnucash.ACCT_TYPE_ASSET,
    'FIXASSET':	gnucash.ACCT_TYPE_ASSET,
    'AP':	gnucash.ACCT_TYPE_PAYABLE,
    'AR':	gnucash.ACCT_TYPE_RECEIVABLE,
    'OCLIAB':	gnucash.ACCT_TYPE_LIABILITY,
    'LTLIAB':	gnucash.ACCT_TYPE_LIABILITY,
    'EQUITY':	gnucash.ACCT_TYPE_EQUITY,
    'INC':	gnucash.ACCT_TYPE_INCOME,
    'EXP':	gnucash.ACCT_TYPE_EXPENSE,
    'EXINC':	gnucash.ACCT_TYPE_INCOME,
    'EXEXP':	gnucash.ACCT_TYPE_EXPENSE,
    }

def lookup_acct_type(type):
    try:
        return AccountTypeMap[type]
    except KeyError:
        print('Unknown QB account type:', type)
        return gnucash.ACCT_TYPE_EXPENSE  # Not sure what else to do

#
# Stuff for reparenting accounts into the GnuCash scheme.
#
AccountRoots = {}
def root_map(type, root, root_type = None):
    if not root_type:
        root_type = type
    AccountRoots[type] = (root, type)
root_map(gnucash.ACCT_TYPE_ASSET, 'Assets')
root_map(gnucash.ACCT_TYPE_BANK, 'Assets', gnucash.ACCT_TYPE_EQUITY)
root_map(gnucash.ACCT_TYPE_EQUITY, 'Equity')
root_map(gnucash.ACCT_TYPE_EXPENSE, 'Expenses')
root_map(gnucash.ACCT_TYPE_INCOME, 'Income')
root_map(gnucash.ACCT_TYPE_LIABILITY, 'Liabilities')
root_map(gnucash.ACCT_TYPE_PAYABLE, 'Liabilities', gnucash.ACCT_TYPE_LIABILITY)
root_map(gnucash.ACCT_TYPE_RECEIVABLE, 'Assets', gnucash.ACCT_TYPE_EQUITY)
# This is not complete of course...

def find_root(root, atype):
    if not Reparent:
        return root
    try:
        rootname, rtype = AccountRoots[atype]
    except KeyError:
        return root
    #
    # Make sure this account exists.
    #
    subroot = root.lookup_by_name(rootname)
    if subroot:
        return subroot
    #
    # Nope, gotta create it.
    #
    subroot = gnucash.Account(book)
    subroot.BeginEdit()
    subroot.SetType(rtype)
    subroot.SetName(rootname)
    subroot.SetCommodity(dollars)
    root.append_child(subroot)
    subroot.CommitEdit()
    return subroot

#
# Transform account names.  For now, just remove slashes, since they
# make GnuCash confused and unhappy.
#
def fixup_acct_name(name):
    return name.replace('/', '')

#
# Walk through the hierarchy to find the right home for this account.
#
def find_parent(name, root):
    sname = name.split(':')
    parent = root
    for acct in sname[:-1]:
        acct = fixup_acct_name(acct)
        parent = parent.lookup_by_name(acct)
        if not parent:
            print('Failed to find container account', acct)
            return root, sname[-1]
    return parent, sname[-1]

#
# We've been given an account name with slashes in it; assume it's already
# in the GnuCash account space and resolve it accordingly.  Create the
# intermediate names if needed.
#
def GC_path(root, name, atype):
    path = name.split('/')
    for dir in path[:-1]:
        new = root.lookup_by_name(dir)
        if not new:
            new = gnucash.Account(book)
            new.BeginEdit()
            new.SetType(atype)
            new.SetName(dir)
            new.SetCommodity(dollars)
            root.append_child(new)
            new.CommitEdit()
        root = new
    return (new, path[-1])

#
# Import a list of accounts.
#
def import_accounts(list):
    root = book.get_root_account()
    for entry in list.entries:
        #
        # Figure out the type and do remapping/reparenting.
        #
        atype = lookup_acct_type(entry['ACCNTTYPE'])
        name = remap.remap(fixup_acct_name(entry['NAME']))
        if name.find('/') >= 0:
            parent, name = GC_path(root, name, atype)
        else:
            parent, name = find_parent(name, find_root(root, atype))
        #
        # Don't make an account that already exists.
        #
        if parent.lookup_by_name(name):
            print('Account %s already exists' % (name))
            continue

        accnum = entry['ACCNUM']
        description = entry['DESC']
        hidden = False
        try:
            if entry['HIDDEN'] == "Y":
                hidden = True
        except KeyError:
            hidden = False

        placeholder = False
        if description == "header":
            placeholder = True
            description = ""

        #
        # Make the account.
        #
        acct = gnucash.Account(book)
        acct.BeginEdit()
        acct.SetType(atype)
        acct.SetName(name)
        acct.SetCommodity(dollars)
        acct.SetCode(accnum)
        acct.SetDescription(description)
        acct.SetHidden(hidden)
        acct.SetPlaceholder(placeholder)
        parent.append_child(acct)
        acct.CommitEdit()
#
# Import the vendor list.
#
def import_vendors(vlist):
    for ventry in vlist.entries:
        name = fix_vname(ventry['NAME'])
        vendor = gnucash_business.Vendor(book = book,
                                         id = book.VendorNextID(),
                                         currency = dollars,
                                         name = name)
        vendor.BeginEdit()
        addr = vendor.GetAddr()
        addr.BeginEdit()
        addr.SetName(ventry['PRINTAS'] or name)
        addr.SetAddr1(ventry['ADDR1'])
        addr.SetAddr2(ventry['ADDR2'])
        addr.SetAddr3(ventry['ADDR3'])
        addr.SetPhone(ventry['PHONE1'])
        addr.CommitEdit()
        if ventry['TAXID']:
            inst = vendor.get_instance()
            gnucash_core_c.gncVendorSetNotes(inst, ventry['TAXID'])
        vendor.CommitEdit()

#
# LWN specific: QB forced the addition of a string to distinguish
# vendors from the other names list, but we don't need it here.
#
asuffix = re.compile(r', +author', re.I)
def fix_vname(name):
    return asuffix.sub('', name)

#
# Import the customer list.
#
def import_customers(clist):
    for centry in clist.entries:
        cust = gnucash_business.Customer(book = book,
                                         id = book.CustomerNextID(),
                                         currency = dollars,
                                         name = centry['NAME'])
        cust.BeginEdit()
        addr = cust.GetAddr()
        addr.BeginEdit()
        addr.SetName(centry['BADDR1'])
        addr.SetAddr1(centry['BADDR2'])
        addr.SetAddr2(centry['BADDR3'])
        addr.SetAddr3(centry['BADDR4'])
        addr.SetAddr4(centry['BADDR5'])
        addr.SetPhone(centry['PHONE1'])
        addr.CommitEdit()
        cust.CommitEdit()
#
# Here we do the argparsery
#
def setupargs():
    p = argparse.ArgumentParser()
    p.add_argument('-c', '--create', required = False, default = False,
                   action = 'store_true', help = 'Create a new gnucash file')
    p.add_argument('-m', '--mapfile', required = False, default = None,
                   help = 'Name of account-name remapping file')
    p.add_argument('-o', '--override', required = False, action = 'store_true',
                   help = 'Override lock on the gnucash file')
    p.add_argument('-r', '--reparent', required = False, action = 'store_true',
                   help = 'Reparent accounts gnucash-style')
    p.add_argument('iif', help = 'The IIF file to process')
    p.add_argument('gcf', help = 'The gnucash file to import into')
    return p

def croak(message):
    sys.stderr.write(message)
    sys.stderr.flush()
    sys.exit(1)
#
# Main program time.
#

#
# Check args and open files
#
args = setupargs().parse_args()
Reparent = args.reparent

try:
    lists = iif.read_IIF(open(args.iif, 'r'))
except IOError as e:
    croak('Unable to open %s, %s' % (args.iif, e))
#
# Open the session.  But if we're creating the file, we have to give it
# a full path or it barfs at us.
#
filename = args.gcf
if args.create:
    filename = 'xml://%s/%s' % (os.getcwd(), filename)
session = gnucash.Session(filename, mode=gnucash.SessionOpenMode.SESSION_NEW_STORE)

#
# Load the mapfile if there is one.
#
if args.mapfile:
    remap.load_mapfile(args.mapfile)

#
# Extract some useful stuff from the GC session
#
book = session.book
ctable = book.get_table()  # Commodity lookup table
# All the world's the US, right??
dollars = ctable.lookup('CURRENCY', 'USD')
#
# Import the lists we understand.
#
Ilist = [ ('ACCNT', import_accounts),
          ('CUST', import_customers),
          ('VEND', import_vendors) ]

for name, importer in Ilist:
    try:
        importer(lists[name])
    except KeyError:
        pass

#
# Clean up and we be done.
#
session.save()
session.end()
sys.exit(0)

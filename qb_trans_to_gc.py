#!/usr/bin/python
#
# A simple QuickBooks transaction importer
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
# sys.path.insert(0, "/my/path/to/site-packages/gnucash")
import csv, argparse
import remap
import gnucash
from gnucash import gnucash_business, gnucash_core_c
import regex

#
# Turn a float value into the gnucash equivalent.
#
SCALE = 1000
def GCVal(value):
    value=value.replace(',', '')
    dollars, cents = list(map(int, value.split('.')))
    ival = dollars*SCALE
    if value[0] != '-':
        ival += cents*(SCALE/100)
    else:
        ival -= cents*(SCALE/100)
    return gnucash.GncNumeric(int(ival), SCALE)
#
# Gnucash implements an account hierarchy but makes us walk it
# ourselves.
#
def LookupAccount(path):
    acct = root_acct
    for component in path.split('/'):
        acct = acct.lookup_by_name(component)
        if not acct:
            return None
    return acct

def SetDate(trans, date):
    month, day, year = list(map(int, date.split('/')))
    # Handle old, two digit dates with an arbitrary 1980 pivot
    if year < 100:
        if year < 80:
            year = year + 2000;
        else:
            year = year + 1900
    trans.SetDate(day, month, year)

acctregex = regex.compile(r'(?<=^\d* [—-] )(.*)')
coderegex = regex.compile(r'^\d*')
def ReadTransaction(reader):
    entry = next(reader)
    print(entry)
    #
    # QB helpfully puts in a couple of crap lines with an empty
    # name.  Drop them.
    #
    try:
        if entry['']:
            return
    except KeyError:
        pass
    #
    # Set up the overall transaction.
    #
    # FIRST LINE TRANSACTION DATA:
    # NOTE: for a Journal export, we assume the first line
    # of a transaction has the Trans #, Type, and Date.
    # Optionally, there may be a 'Num' value
    # 
    trans = gnucash.Transaction(book)
    trans.BeginEdit()
    trans.SetCurrency(dollars)

    description = ( "(qb: " +
                    "Type: " +  entry['Type'])

    try:
        if entry['Num']:
            description = description + " Num: " + entry['Num']
    except KeyError:
        pass

    description = description + ")"
    trans.SetDescription(description)

    trans.SetNum(entry['Trans #'])
    SetDate(trans, entry['Date'])

    # for a Journal Export, we assume entries are reconciled
    # reconciled status will be invalidated 
    # if there's an imbalance is found
    reconciled = 'y' 
    #
    # Basic theory here (FOR JOURNAL EXPORT): 
    # QB dumps a pile of splits into the file
    # without grouping them into transactions.  The signal that we've
    # found the last split is that the balance goes to zero.  This
    # *could* screw us, since that is possible in a legitimate transaction.
    # But with luck it won't actually happen.
    #
    # Note the the overall entry is also the first split.
    #
    while True:
        #
        # Read in the Split (aka Leg) of the transaction
        #
        
        # 
        # first evaluate the debit and credit values
        #
        debit = None
        credit = None
        try:
            if entry['Debit']:
                debit = entry['Debit']
            if entry['Credit']:
                credit = entry['Credit']
        except KeyError:
            pass

        #
        # Are we done for this transaction?
        # The last entry should have just credit AND debit entries. 
        #
        if (debit is not None) and (credit is not None):
            if credit != debit:
                reconciled = 'n' #mark imbalanced transaction as needing reconciliation
            break

        #
        # Put together the split info.
        #
        split = gnucash.Split(book)


        #
        # NOTE: I'm interpreting the debit and credit
        #       values (in relation to the account) 
        #       as swapped in the Journal export.
        #  So, for a given split, 
        #  - a debit value seen is a credit (positive num) to the account  
        #  - a credit value seen is a debit (negative num) to the account  
        #
        if (debit is not None) and (credit is None):
            split.SetValue(GCVal(debit))
            split.SetAmount(GCVal(debit))
        if (debit is None) and (credit is not None):
            split.SetValue(GCVal(credit) * -1.0)
            split.SetAmount(GCVal(credit) * -1.0)

        acct_matches = acctregex.search(entry['Account'])
        code_matches = coderegex.search(entry['Account'])
        if ((acct_matches is None) or 
            (len(acct_matches.groups()) == 0) or 
            (code_matches is None)):
            print('Unknown account', entry['Account'])
            account = LookupAccount('Miscellaneous')
            entry = next(reader)
            continue

        code = code_matches.group(0)
        account = root_acct.lookup_by_code(code)
        split.SetAccount(account)

        qb_migration_memo = entry['Memo']

        try:
            if entry['Name']:
                qb_migration_memo = (qb_migration_memo + 
                    " (qb: " +
                    "name:\"" + entry['Name'] + 
                    ") ")
        except KeyError:
            pass

        split.SetMemo(qb_migration_memo)
        split.SetParent(trans)
        gnucash_core_c.xaccSplitSetReconcile(split.get_instance(),
                                             reconciled)

        # move to next leg of this transaction
        entry = next(reader)
    #
    # Finalize and commit transaction 
    #
    trans.CommitEdit()

#
# Check args and open files
#
#
# Here we do the argparsery
#
def setupargs():
    p = argparse.ArgumentParser()
    p.add_argument('-m', '--mapfile', required = False, default = None,
                   help = 'Name of account-name remapping file')
    p.add_argument('-o', '--override', required = False, action = 'store_true',
                   help = 'Override lock on the gnucash file', default = False)
    p.add_argument('csvfile', help = 'The CSV file to process')
    p.add_argument('gcfile', help = 'The gnucash file to import into')
    return p
args = setupargs().parse_args()

try:
    tfile = open(args.csvfile, 'r')
except IOError as e:
    print('Unable to open %s, %s' % (args.csvfile, e))
    sys.exit(1)
#
# Load the mapfile if there is one.
#
if args.mapfile:
    remap.load_mapfile(args.mapfile)
#
# Set up with gnucash
#
session = gnucash.Session(args.gcfile, mode=gnucash.SessionOpenMode.SESSION_NORMAL_OPEN)
book = session.book
dollars = book.get_table().lookup('CURRENCY', 'USD')
root_acct = book.get_root_account()

#
# Plow through the data.
#
reader = csv.DictReader(tfile)
while True:
    try:
        ReadTransaction(reader)
    except StopIteration:
        break

session.save()
session.end()

import numpy as np
from rdkit import Chem
import multiprocessing
from torch_geometric.data import Data
import torch.nn as nn
import matplotlib.pyplot as plt
from rdkit import Chem
from rdkit.Chem import AllChem
import numpy as np
import torch
import torch.nn.functional as F
from torch.nn import Linear
from torch.nn import BatchNorm1d
from torch.utils.data import Dataset
from torch_geometric.nn import GCNConv
from torch_geometric.nn import ChebConv
from torch_geometric.nn import global_add_pool, global_mean_pool
from torch_geometric.data import DataLoader
from torch_scatter import scatter_mean
import pandas as pd
from sklearn.model_selection import train_test_split
from random import randrange
import itertools
from torch_geometric.nn import EdgeConv
import random
import os
import time
from tqdm import tqdm
from sklearn.metrics import mean_squared_error
from sklearn.metrics import mean_absolute_error
from sklearn.metrics import r2_score
from scipy.stats import spearmanr

import pickle, gzip
from . import config


def set_seed(seed):
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    np.random.seed(seed)
    random.seed(seed)
    os.environ['PYTHONHASHSEED'] = str(seed)

def one_of_k_encoding(x, allowable_set):
    if x not in allowable_set:
        raise Exception("input {0} not in allowable set{1}:".format(x, allowable_set))
    return list(map(lambda s: x == s, allowable_set))
 
def one_of_k_encoding_unk(x, allowable_set):
    """Maps inputs not in the allowable set to the last element."""
    if x not in allowable_set:
        x = allowable_set[-1]
    return list(map(lambda s: x == s, allowable_set))
 
def get_intervals(l):
    """For list of lists, gets the cumulative products of the lengths"""
    intervals = len(l) * [0]
    # Initalize with 1
    intervals[0] = 1
    for k in range(1, len(l)):
        intervals[k] = (len(l[k]) + 1) * intervals[k - 1]
    return intervals
 
def safe_index(l, e):
    """Gets the index of e in l, providing an index of len(l) if not found"""
    try:
        return l.index(e)
    except:
        return len(l)

def best_fit_slope_and_intercept(xs,ys):
    m = (((np.mean(xs)*np.mean(ys)) - np.mean(xs*ys)) /
         ((np.mean(xs)*np.mean(xs)) - np.mean(xs*xs)))
    
    b = np.mean(ys) - m*np.mean(xs)
    
    return m, b

possible_atom_list = [
    'C', 'N', 'O', 'S', 'F', 'P', 'Cl', 'Mg', 'Na', 'Br', 'Fe', 'Ca', 'Cu',
    'Mc', 'Pd', 'Pb', 'K', 'I', 'Al', 'Ni', 'Mn'
]
possible_numH_list = [0, 1, 2, 3, 4]
possible_valence_list = [0, 1, 2, 3, 4, 5, 6]
possible_formal_charge_list = [-3, -2, -1, 0, 1, 2, 3]
possible_hybridization_list = [
    Chem.rdchem.HybridizationType.SP, Chem.rdchem.HybridizationType.SP2,
    Chem.rdchem.HybridizationType.SP3, Chem.rdchem.HybridizationType.SP3D,
    Chem.rdchem.HybridizationType.SP3D2
]
possible_number_radical_e_list = [0, 1, 2]
possible_chirality_list = ['R', 'S']
 
reference_lists = [
    possible_atom_list, possible_numH_list, possible_valence_list,
    possible_formal_charge_list, possible_number_radical_e_list,
    possible_hybridization_list, possible_chirality_list
]
 
intervals = get_intervals(reference_lists)


def get_feature_list(atom):
    features = 6 * [0]
    features[0] = safe_index(possible_atom_list, atom.GetSymbol())
    features[1] = safe_index(possible_numH_list, atom.GetTotalNumHs())
    features[2] = safe_index(possible_valence_list, atom.GetImplicitValence())
    features[3] = safe_index(possible_formal_charge_list, atom.GetFormalCharge())
    features[4] = safe_index(possible_number_radical_e_list,
                           atom.GetNumRadicalElectrons())
    features[5] = safe_index(possible_hybridization_list, atom.GetHybridization())
    return features
 
def features_to_id(features, intervals):
    """Convert list of features into index using spacings provided in intervals"""
    id = 0
    for k in range(len(intervals)):
        id += features[k] * intervals[k]

        # Allow 0 index to correspond to null molecule 1
        id = id + 1
    return id

def id_to_features(id, intervals):
    features = 6 * [0]

    # Correct for null
    id -= 1

    for k in range(0, 6 - 1):
        # print(6-k-1, id)
        features[6 - k - 1] = id // intervals[6 - k - 1]
        id -= features[6 - k - 1] * intervals[6 - k - 1]
        # Correct for last one
        features[0] = id
    return features

def atom_to_id(atom):
    """Return a unique id corresponding to the atom type"""
    features = get_feature_list(atom)
    return features_to_id(features, intervals)

def atom_features(atom, bool_id_feat=False, explicit_H=False, use_chirality=False):
    if bool_id_feat:
        return np.array([atom_to_id(atom)])
    else:
        from rdkit import Chem

        results = one_of_k_encoding_unk(atom.GetSymbol(),['Ag','Al','As','B','Br','C','Ca','Cd','Cl','Cu','F',
                                                              'Fe','Ge','H','Hg','I','K','Li','Mg','Mn','N','Na',
                                                              'O','P','Pb','Pt','S','Se','Si','Sn','Sr','Tl','Zn',
                                                              'Unknown'])\
        + one_of_k_encoding(atom.GetDegree(),[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]) + \
              one_of_k_encoding_unk(atom.GetImplicitValence(), [0, 1, 2, 3, 4, 5, 6]) + \
              [atom.GetFormalCharge(), atom.GetNumRadicalElectrons()] + \
                one_of_k_encoding_unk(atom.GetHybridization(), [
                Chem.rdchem.HybridizationType.SP, Chem.rdchem.HybridizationType.SP2,
                Chem.rdchem.HybridizationType.SP3, Chem.rdchem.HybridizationType.
                                    SP3D, Chem.rdchem.HybridizationType.SP3D2
              ]) + [atom.GetIsAromatic()] 

        if not explicit_H:
            results = results + one_of_k_encoding_unk(atom.GetTotalNumHs(),
                                                [0, 1, 2, 3, 4])
        if use_chirality:
            try:
                results = results + one_of_k_encoding_unk(atom.GetProp('_CIPCode'),
                                                          ['R', 'S']) + [atom.HasProp('_ChiralityPossible')]
            except:
                results = results + [False, False] + [atom.HasProp('_ChiralityPossible')]
 
        return np.array(results)

def bond_features(bond, use_chirality=False):
    from rdkit import Chem
    bt = bond.GetBondType()
    bond_feats = [
      bt == Chem.rdchem.BondType.SINGLE, bt == Chem.rdchem.BondType.DOUBLE,
      bt == Chem.rdchem.BondType.TRIPLE, bt == Chem.rdchem.BondType.AROMATIC,
      bond.GetIsConjugated(),
      bond.IsInRing()]
    
    if use_chirality:
        bond_feats = bond_feats + one_of_k_encoding_unk(str(bond.GetStereo()),
        ["STEREONONE", "STEREOANY", "STEREOZ", "STEREOE"])
    return np.array(bond_feats)


def get_bond_pair(mol):
    bonds = mol.GetBonds()
    res = [[],[]]
    for bond in bonds:
        res[0] += [bond.GetBeginAtomIdx(), bond.GetEndAtomIdx()]
        res[1] += [bond.GetEndAtomIdx(), bond.GetBeginAtomIdx()]
    return res



def creatData(smiles, y, idx):   
    mol = Chem.MolFromSmiles(smiles)
    atoms = mol.GetAtoms()
    bonds = mol.GetBonds()
    node_f= [atom_features(atom) for atom in atoms]
    edge_index = get_bond_pair(mol)

    edge_attr=[]
    for bond in bonds:
        edge_attr.append(bond_features(bond, use_chirality=False))
        edge_attr.append(bond_features(bond, use_chirality=False))
    
    data = Data(x=torch.tensor(node_f, dtype=torch.float),
              edge_index=torch.tensor(edge_index, dtype=torch.long),
              edge_attr=torch.tensor(edge_attr,dtype=torch.float),
                y=torch.tensor([y],dtype=torch.float),
                idx = torch.tensor([idx],dtype=torch.long),

              )
    return data

def create_data_list(dfx):
    data_list = []
    for i in tqdm(range(dfx.shape[0])):
        smiles = dfx.smiles.values[i]
        y  = dfx.log_sol.values[i]
        data_list.append(creatData(smiles=smiles, y=y, idx=i))
    return data_list



def create_data():
    
    train = pd.read_csv(config.data_dir+"train.csv")
    val = pd.read_csv(config.data_dir+"val.csv")
    test = pd.read_csv(config.data_dir+"test.csv")

    train.reset_index(drop=True, inplace=True)
    val.reset_index(drop=True, inplace=True)
    test.reset_index(drop=True, inplace=True)

    print("checking for duplicates")
    if len(list(set(train.smiles.values).intersection(set(test.smiles.values)) )) == 0:
        print("no duplicates in train and test")

    if len(list(set(train.smiles.values).intersection(set(val.smiles.values)) )) == 0:
        print("no duplicates in train and valid")

    if len(list( set(test.smiles.values).intersection(set(val.smiles.values)) )) == 0:
        print("no duplicates in test and valid")
    print(" ")

    print(f"train set size = {train.shape}, unique smiles in the train set = {len(set(train.smiles.values))}")
    print(f"train set size = {val.shape}, unique smiles in the valid set = {len(set(val.smiles.values))}")
    print(f"train set size = {test.shape}, unique smiles in the test set = {len(set(test.smiles.values))}")
    print(" ")
    
    print("creating train data")
    train_X = create_data_list(train)
    print("creating valid data")
    val_X = create_data_list(val)
    print("creating test data")
    test_X = create_data_list(test)

    with gzip.open(config.gnn_data_dir+"train.pkl.gz", "wb") as f:
        pickle.dump(train_X, f, protocol=4)
    with gzip.open(config.gnn_data_dir+"val.pkl.gz", "wb") as f:
        pickle.dump(val_X, f, protocol=4)
    with gzip.open(config.gnn_data_dir+"test.pkl.gz", "wb") as f:
        pickle.dump(test_X, f, protocol=4)
        
        
        

class EarlyStopping:
    """Early stops the training if validation loss doesn't improve after a given patience."""
    def __init__(self, patience=7, verbose=False, delta=0, chkpoint_name = 'gnn_best.pt' ):
        """
        Args:
            patience (int): How long to wait after last time validation loss improved.
                            Default: 7
            verbose (bool): If True, prints a message for each validation loss improvement. 
                            Default: False
            delta (float): Minimum change in the monitored quantity to qualify as an improvement.
                            Default: 0
        """
        self.patience = patience
        self.verbose = verbose
        self.counter = 0
        self.best_score = None
        self.early_stop = False
        self.val_loss_min = np.Inf
        self.delta = delta
        self.chkpoint_name = chkpoint_name

    def __call__(self, val_loss, model):

        score = -val_loss

        if self.best_score is None:
            self.best_score = score
            self.save_checkpoint(val_loss, model)
        elif score < self.best_score + self.delta:
            self.counter += 1
            print(f'EarlyStopping counter: {self.counter} out of {self.patience}')
            if self.counter >= self.patience:
                self.early_stop = True
        else:
            self.best_score = score
            self.save_checkpoint(val_loss, model)
            self.counter = 0

    def save_checkpoint(self, val_loss, model):
	# Ensure the parent directory exists
        checkpoint_dir = os.path.dirname(self.chkpoint_name)
        if checkpoint_dir and not os.path.exists(checkpoint_dir):
            os.makedirs(checkpoint_dir)
        '''Saves model when validation loss decrease.'''
        if self.verbose:
            print(f'Validation loss decreased ({self.val_loss_min:.6f} --> {val_loss:.6f}).  Saving model ...')
        torch.save(model.state_dict(), self.chkpoint_name)
        self.val_loss_min = val_loss

        
def test_fn(loader, model, device):
    model.eval()
    with torch.no_grad():
        target, predicted = [], []
        for data in loader:
            data = data.to(device)
            output = model(data)
            pred = output

            target += list(data.y.cpu().numpy().ravel() )
            predicted += list(pred.cpu().numpy().ravel() )

    return mean_squared_error(y_true=target, y_pred=predicted)


def test_fn_plotting(loader, model, device):
    
    model.eval()
    
    with torch.no_grad():
        target, predicted = [], []
        for data in loader:
            data = data.to(device)
            output = model(data)
            pred = output

            target += list(data.y.cpu().numpy().ravel() )
            predicted += list(pred.cpu().numpy().ravel() )

    return np.array(target), np.array(predicted)


def get_results(db_name, loader, model, device):
    
    print(f"{db_name} results")
    test_t, test_p = test_fn_plotting(loader, model, device)

    r2 = r2_score(y_pred = test_p, y_true = test_t)
    rmse = mean_squared_error(y_pred = test_p, y_true = test_t)**.5
    sp = spearmanr(test_p, test_t)[0]
    mae = mean_absolute_error(y_pred=test_p, y_true=test_t)

    print("r2: {0:.4f}".format(r2) )
    print("rmse: {0:.4f}".format(rmse) )
    print("sp: {0:.4f}".format(sp) )
    print("mae: {0:.4f}".format(mae) )

    plt.figure()
    plt.plot( test_t, test_p, 'o')
    plt.xlabel("True (logS)", fontsize=15, fontweight='bold');
    plt.ylabel("Predicted (logS)", fontsize=15, fontweight='bold');
    plt.show()


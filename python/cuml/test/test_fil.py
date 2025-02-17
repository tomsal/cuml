# Copyright (c) 2019, NVIDIA CORPORATION.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import numpy as np
import pytest
import os

from cuml import ForestInference
from cuml.test.utils import array_equal, unit_param, \
    quality_param, stress_param
from cuml.utils.import_utils import has_xgboost, has_lightgbm

from sklearn.datasets import make_classification, make_regression
from sklearn.metrics import accuracy_score, mean_squared_error
from sklearn.model_selection import train_test_split

if has_xgboost():
    import xgboost as xgb

    def simulate_data(m, n, k=2, random_state=None, classification=True):
        if classification:
            features, labels = make_classification(n_samples=m,
                                                   n_features=n,
                                                   n_informative=int(n/5),
                                                   n_classes=k,
                                                   random_state=random_state)
        else:
            features, labels = make_regression(n_samples=m,
                                               n_features=n,
                                               n_informative=int(n/5),
                                               n_targets=1,
                                               random_state=random_state)
        return np.c_[features].astype(np.float32), \
            np.c_[labels].astype(np.float32).flatten()


def _build_and_save_xgboost(model_path,
                            X_train,
                            y_train,
                            classification=True,
                            num_rounds=5,
                            xgboost_params={}):
    """Trains a small xgboost classifier and saves it to model_path"""
    dtrain = xgb.DMatrix(X_train, label=y_train)

    # instantiate params
    params = {'silent': 1}

    # learning task params
    if classification:
        params['eval_metric'] = 'error'
        params['objective'] = 'binary:logistic'
    else:
        params['eval_metric'] = 'error'
        params['objective'] = 'reg:squarederror'
        params['base_score'] = 0.0

    params['max_depth'] = 25
    params.update(xgboost_params)

    bst = xgb.train(params, dtrain, num_rounds)
    bst.save_model(model_path)
    return bst


@pytest.mark.parametrize('n_rows', [unit_param(1000),
                                    quality_param(10000),
                                    stress_param(500000)])
@pytest.mark.parametrize('n_columns', [unit_param(11),
                                       quality_param(100),
                         stress_param(1000)])
@pytest.mark.parametrize('num_rounds', [unit_param(1),
                                        unit_param(5),
                                        quality_param(50),
                                        stress_param(90)])
@pytest.mark.skipif(has_xgboost() is False, reason="need to install xgboost")
def test_fil_classification(n_rows, n_columns, num_rounds, tmp_path):
    # settings
    classification = True  # change this to false to use regression
    n_rows = n_rows  # we'll use 1 millions rows
    n_columns = n_columns
    n_categories = 2
    random_state = np.random.RandomState(43210)

    X, y = simulate_data(n_rows, n_columns, n_categories,
                         random_state=random_state,
                         classification=classification)
    # identify shape and indices
    n_rows, n_columns = X.shape
    train_size = 0.80

    X_train, X_validation, y_train, y_validation = train_test_split(
        X, y, train_size=train_size, random_state=0)

    model_path = os.path.join(tmp_path, 'xgb_class.model')

    bst = _build_and_save_xgboost(model_path, X_train, y_train,
                                  num_rounds, classification)

    dvalidation = xgb.DMatrix(X_validation, label=y_validation)
    xgb_preds = bst.predict(dvalidation)
    xgb_preds_int = np.around(xgb_preds)

    xgb_acc = accuracy_score(y_validation, xgb_preds > 0.5)

    print("Reading the saved xgb model")

    fm = ForestInference.load(model_path,
                              algo='BATCH_TREE_REORG',
                              output_class=True,
                              threshold=0.50)
    fil_preds = np.asarray(fm.predict(X_validation))
    fil_acc = accuracy_score(y_validation, fil_preds)

    print("XGB accuracy = ", xgb_acc, " ForestInference accuracy: ", fil_acc)
    assert fil_acc == pytest.approx(xgb_acc, 0.01)
    assert array_equal(fil_preds, xgb_preds_int)


@pytest.mark.parametrize('n_rows', [unit_param(1000), quality_param(10000),
                         stress_param(500000)])
@pytest.mark.parametrize('n_columns', [unit_param(11), quality_param(100),
                         stress_param(1000)])
@pytest.mark.parametrize('num_rounds', [unit_param(5), quality_param(10),
                         stress_param(90)])
@pytest.mark.parametrize('max_depth', [unit_param(3),
                                       unit_param(7),
                                       stress_param(11)])
@pytest.mark.skipif(has_xgboost() is False, reason="need to install xgboost")
def test_fil_regression(n_rows, n_columns, num_rounds, tmp_path, max_depth):
    # settings
    classification = False  # change this to false to use regression
    n_rows = n_rows  # we'll use 1 millions rows
    n_columns = n_columns
    random_state = np.random.RandomState(43210)

    X, y = simulate_data(n_rows, n_columns,
                         random_state=random_state,
                         classification=classification)
    # identify shape and indices
    n_rows, n_columns = X.shape
    train_size = 0.80

    X_train, X_validation, y_train, y_validation = train_test_split(
        X, y, train_size=train_size, random_state=0)

    model_path = os.path.join(tmp_path, 'xgb_reg.model')
    bst = _build_and_save_xgboost(model_path, X_train,
                                  y_train,
                                  num_rounds,
                                  classification,
                                  xgboost_params={'max_depth': max_depth})

    dvalidation = xgb.DMatrix(X_validation, label=y_validation)
    xgb_preds = bst.predict(dvalidation)

    xgb_mse = mean_squared_error(y_validation, xgb_preds)
    print("Reading the saved xgb model")
    fm = ForestInference.load(model_path,
                              algo='BATCH_TREE_REORG',
                              output_class=False)
    fil_preds = np.asarray(fm.predict(X_validation))
    fil_mse = mean_squared_error(y_validation, fil_preds)

    print("XGB accuracy = ", xgb_mse, " Forest accuracy: ", fil_mse)
    assert fil_mse == pytest.approx(xgb_mse, 0.01)
    assert array_equal(fil_preds, xgb_preds)


@pytest.fixture(scope="session")
def small_classifier_and_preds(tmpdir_factory):
    X, y = simulate_data(100, 10,
                         random_state=43210,
                         classification=True)

    model_path = str(tmpdir_factory.mktemp("models").join("small_class.model"))
    bst = _build_and_save_xgboost(model_path, X, y)
    # just do within-sample since it's not an accuracy test
    dtrain = xgb.DMatrix(X, label=y)
    xgb_preds = bst.predict(dtrain)

    return (model_path, X, xgb_preds)


@pytest.mark.skipif(has_xgboost() is False, reason="need to install xgboost")
@pytest.mark.parametrize('algo', ['NAIVE', 'TREE_REORG', 'BATCH_TREE_REORG',
                                  'naive', 'tree_reorg', 'batch_tree_reorg'])
def test_output_algos(algo, small_classifier_and_preds):
    model_path, X, xgb_preds = small_classifier_and_preds
    fm = ForestInference.load(model_path,
                              algo=algo,
                              output_class=True,
                              threshold=0.50)

    xgb_preds_int = np.around(xgb_preds)
    fil_preds = np.asarray(fm.predict(X))
    assert np.allclose(fil_preds, xgb_preds_int, 1e-3)


@pytest.mark.skipif(has_xgboost() is False, reason="need to install xgboost")
@pytest.mark.parametrize('storage_type',
                         ['AUTO', 'DENSE', 'SPARSE', 'auto', 'dense',
                          'sparse'])
def test_output_storage_type(storage_type, small_classifier_and_preds):
    model_path, X, xgb_preds = small_classifier_and_preds
    fm = ForestInference.load(model_path,
                              algo='NAIVE',
                              output_class=True,
                              storage_type=storage_type,
                              threshold=0.50)

    xgb_preds_int = np.around(xgb_preds)
    fil_preds = np.asarray(fm.predict(X))
    assert np.allclose(fil_preds, xgb_preds_int, 1e-3)


@pytest.mark.parametrize('output_class', [True, False])
@pytest.mark.skipif(has_xgboost() is False, reason="need to install xgboost")
def test_thresholding(output_class, small_classifier_and_preds):
    model_path, X, xgb_preds = small_classifier_and_preds
    fm = ForestInference.load(model_path,
                              algo='TREE_REORG',
                              output_class=output_class,
                              threshold=0.50)
    fil_preds = np.asarray(fm.predict(X))
    if output_class:
        assert ((fil_preds != 0.0) & (fil_preds != 1.0)).sum() == 0
    else:
        assert ((fil_preds != 0.0) & (fil_preds != 1.0)).sum() > 0


@pytest.mark.skipif(has_xgboost() is False, reason="need to install xgboost")
def test_output_args(small_classifier_and_preds):
    model_path, X, xgb_preds = small_classifier_and_preds
    fm = ForestInference.load(model_path,
                              algo='TREE_REORG',
                              output_class=False,
                              threshold=0.50)
    X = np.asarray(X)
    fil_preds = fm.predict(X)
    assert np.allclose(fil_preds, xgb_preds, 1e-3)


@pytest.mark.skipif(has_lightgbm() is False, reason="need to install lightgbm")
def test_lightgbm(tmp_path):
    import lightgbm as lgb
    X, y = simulate_data(100, 10,
                         random_state=43210,
                         classification=True)
    train_data = lgb.Dataset(X, label=y)
    param = {'objective': 'binary',
             'metric': 'binary_logloss'}
    num_round = 5
    bst = lgb.train(param, train_data, num_round)
    gbm_preds = bst.predict(X)

    model_path = str(os.path.join(tmp_path,
                                  'lgb.model'))
    bst.save_model(model_path)
    fm = ForestInference.load(model_path,
                              algo='TREE_REORG',
                              output_class=False,
                              model_type="lightgbm")

    fil_preds = np.asarray(fm.predict(X))
    assert np.allclose(gbm_preds, fil_preds, 1e-3)

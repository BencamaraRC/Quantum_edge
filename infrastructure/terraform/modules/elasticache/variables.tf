variable "environment" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "vpc_cidr" {
  type = string
}

variable "subnet_ids" {
  type = list(string)
}

variable "node_type" {
  type = string
}

variable "num_cache_clusters" {
  type = number
}
